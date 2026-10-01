// All calls are same-origin (this widget is served by the same FastAPI app as
// the API), so no Grist plugin API and no CORS config is needed here — every
// Grist read/write happens on the backend, authenticated with its own API key
// (see docs/08-grist-ui-design.md, "Why the widget doesn't talk to Grist directly").

function el(id) { return document.getElementById(id); }

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderTable(rows, columns, options) {
  const { limit = 200 } = options || {};
  if (!rows || rows.length === 0) return "<p><em>No rows.</em></p>";
  const shown = rows.slice(0, limit);
  const header = columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = shown
    .map((row) => `<tr>${columns.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`)
    .join("");
  const more = rows.length > shown.length
    ? `<p class="hint">Showing ${shown.length} of ${rows.length} rows — the full set is in the matching Grist table.</p>`
    : "";
  return `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>${more}`;
}

// FastAPI puts a dict `detail` through verbatim, which is how the solve endpoint
// returns structured diagnostics alongside a human-readable message. Keep the object
// so callers can render the lock conflicts as something better than a JSON blob.
async function apiCall(path, options) {
  const resp = await fetch(path, options);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = body.detail;
    const err = new Error(
      typeof detail === "string" ? detail
        : (detail && detail.message) ? detail.message
        : resp.statusText
    );
    err.status = resp.status;
    err.detail = detail;
    throw err;
  }
  return body;
}

function showError(resultId, err) {
  let html = `<p class="status-err">${escapeHtml(err.message || err)}</p>`;
  const conflicts = err.detail && err.detail.lock_conflicts;
  if (conflicts && conflicts.length) {
    html += `<p><strong>Locks that cannot all hold:</strong></p>`;
    html += `<ul class="conflicts">` + conflicts.map((c) =>
      `<li><strong>${escapeHtml(c.kind)}</strong> — ${escapeHtml(c.detail)}` +
      (c.cells && c.cells.length ? `<br><span class="hint">locked: ${escapeHtml(c.cells.join(", "))}</span>` : "") +
      `</li>`
    ).join("") + `</ul>`;
  }
  if (err.detail && err.detail.diagnostics) {
    html += `<pre class="diagnostics">${escapeHtml(err.detail.diagnostics)}</pre>`;
  }
  el(resultId).innerHTML = html;
}

function busy(resultId, message) {
  el(resultId).innerHTML = `<p>${escapeHtml(message)}</p>`;
}

async function refreshState() {
  const banner = el("state-banner");
  const warnBanner = el("lock-warnings");
  try {
    const state = await apiCall("/api/state");
    banner.classList.remove("error");
    const where = state.horizon_exhausted
      ? `Horizon complete (${state.horizon_start} to ${state.horizon_end}).`
      : `Planning ${state.current_month} (horizon ${state.horizon_start}–${state.horizon_end}, `
        + `closed through ${state.closed_through || "nothing yet"}).`;
    const working = state.working_cells
      ? `Working assignment: ${state.working_cells} cell(s), ${state.working_hours}h, `
        + `${state.working_locked} locked. Iteration ${state.iteration}`
        + (state.iteration_source ? ` (${state.iteration_source})` : "")
        + (state.unsaved_tweaks ? ` — <strong>unsaved hand-edits</strong>, the next solve will save them first.` : ".")
      : `No working assignment yet — import a ballpark in step 1, or solve from scratch in step 3.`;
    const pre = state.num_pre_assignments
      ? ` ${state.num_pre_assignments} bounds-shaped pre-assignment(s) pending.`
      : "";
    banner.innerHTML = `${escapeHtml(where)} ${working}${escapeHtml(pre)}`;

    if (state.lock_warnings && state.lock_warnings.length) {
      warnBanner.hidden = false;
      warnBanner.innerHTML = `<strong>Locks being ignored:</strong><ul>`
        + state.lock_warnings.map((c) => `<li>${escapeHtml(c.detail)}</li>`).join("")
        + `</ul>`;
    } else {
      warnBanner.hidden = true;
    }
  } catch (err) {
    banner.classList.add("error");
    banner.textContent = `Couldn't load plan state: ${err.message}`;
  }
}

// --- 1. Import the ballpark ------------------------------------------------------

async function submitBallpark(dryRun) {
  const resultId = "result-import";
  const fileInput = el("ballpark-file");
  if (!fileInput.files.length) {
    el(resultId).innerHTML = `<p class="status-warn">Choose a CSV or JSON file first.</p>`;
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  const params = new URLSearchParams({
    dry_run: String(dryRun),
    make_eligible: String(el("make-eligible").checked),
  });
  busy(resultId, dryRun ? "Auditing…" : "Importing…");
  try {
    const body = await apiCall(`/api/working-assignment/import?${params}`, { method: "POST", body: formData });
    const counts = Object.entries(body.status_counts || {})
      .map(([status, count]) => `${status}: ${count}`).join(", ");

    let html = dryRun
      ? `<p class="status-ok">Audited ${body.parsed} row(s) — nothing written.</p>`
      : `<p class="status-ok">Imported ${body.applied} of ${body.parsed} row(s)`
        + (body.iteration ? ` as iteration ${body.iteration}` : "") + `.</p>`;

    if (body.dropped) {
      html += `<p class="status-warn">${body.dropped} row(s) the solver can't use`
        + (dryRun ? "" : " were skipped") + `.</p>`;
    }
    if (body.needs_bounds && body.needs_bounds.length && !body.made_eligible) {
      html += `<p class="status-warn">${body.needs_bounds.length} cell(s) have no eligible `
        + `<code>Bounds</code> row. Re-run with "Also make ineligible pairs eligible" to open them.</p>`;
    }
    if (body.made_eligible) {
      html += `<p class="status-ok">Added ${body.made_eligible} permissive <code>Bounds</code> row(s).</p>`;
    }
    html += `<p>${escapeHtml(counts)}</p>`;
    // Worst first: audit rows are already sorted unusable-before-clean by the backend.
    html += renderTable(body.audit_rows, ["project_id", "person_id", "month", "hours", "locked", "status", "applied", "detail"]);
    el(resultId).innerHTML = html;
    refreshState();
  } catch (err) {
    showError(resultId, err);
  }
}

el("btn-audit").addEventListener("click", () => submitBallpark(true));
el("btn-import").addEventListener("click", () => submitBallpark(false));

// --- 2. Tweak and lock -----------------------------------------------------------

async function setLocks(locked) {
  const resultId = "result-tweak";
  const params = new URLSearchParams({
    locked: String(locked),
    only_nonzero: String(el("lock-nonzero").checked),
  });
  for (const [key, id] of [["project_id", "lock-project"], ["person_id", "lock-person"], ["month", "lock-month"]]) {
    const value = el(id).value.trim();
    if (value) params.set(key, value);
  }
  busy(resultId, locked ? "Locking…" : "Unlocking…");
  try {
    const body = await apiCall(`/api/working-assignment/locks?${params}`, { method: "POST" });
    el(resultId).innerHTML = body.changed
      ? `<p class="status-ok">${locked ? "Locked" : "Unlocked"} ${body.changed} cell(s). `
        + `${body.locked_now} of ${body.total_cells} now locked.</p>`
      : `<p class="status-warn">Nothing matched, or every match was already `
        + `${locked ? "locked" : "unlocked"}. ${body.locked_now} of ${body.total_cells} locked.</p>`;
    refreshState();
  } catch (err) {
    showError(resultId, err);
  }
}

el("btn-lock").addEventListener("click", () => setLocks(true));
el("btn-unlock").addEventListener("click", () => setLocks(false));

el("btn-view-working").addEventListener("click", async () => {
  const resultId = "result-tweak";
  busy(resultId, "Loading…");
  try {
    const body = await apiCall("/api/working-assignment");
    el(resultId).innerHTML =
      `<p>${body.rows.length} cell(s), ${body.total_hours}h, ${body.num_locked} locked.</p>` +
      renderTable(body.rows, ["month", "project_id", "person_id", "hours_assigned", "locked"]);
  } catch (err) {
    showError(resultId, err);
  }
});

// --- 3. Solve --------------------------------------------------------------------

el("btn-solve").addEventListener("click", async () => {
  const resultId = "result-solve";
  const adherence = el("adherence").value;
  busy(resultId, "Solving…");
  try {
    const body = await apiCall(`/api/run-planning?adherence=${encodeURIComponent(adherence)}`, { method: "POST" });
    const counts = Object.entries(body.diff_counts || {})
      .map(([status, count]) => `${status}: ${count}`).join(", ");

    let html = `<p class="status-ok">Feasible. Objective ${body.objective?.toFixed(4) ?? "n/a"}, `
      + `${body.wall_time_seconds}s, saved as iteration ${body.iteration}.</p>`;
    if (body.tweaks_saved_as) {
      html += `<p class="hint">Your hand-edits were saved first as iteration ${body.tweaks_saved_as} `
        + `— restore that in step 4 to get them back.</p>`;
    }
    html += `<p>${body.num_locked} locked cell(s) held. Changes: ${escapeHtml(counts || "none")}.</p>`;
    if (body.lock_warnings && body.lock_warnings.length) {
      html += `<p class="status-warn">${body.lock_warnings.length} lock(s) ignored — see the banner above.</p>`;
    }
    html += renderTable(body.diff_rows,
      ["status", "month", "project_id", "person_id", "pre_assigned_hours", "solved_hours", "delta", "locked"]);
    if (body.pre_assignment_diff && body.pre_assignment_diff.length) {
      html += `<h3>Bounds-shaped pre-assignments</h3>`
        + renderTable(body.pre_assignment_diff,
            ["status", "project_id", "person_id", "pre_assigned_hours", "solved_hours", "delta"]);
    }
    el(resultId).innerHTML = html;
    refreshState();
    loadHistory();
  } catch (err) {
    showError(resultId, err);
  }
});

// --- 4. Iterations & going back --------------------------------------------------

async function loadHistory() {
  const resultId = "result-history";
  try {
    const body = await apiCall("/api/working-assignment/history");
    if (!body.iterations.length) {
      el(resultId).innerHTML = `<p><em>No iterations saved yet.</em></p>`;
      return;
    }
    const rows = body.iterations.map((it) => `
      <tr>
        <td>${escapeHtml(it.iteration)}</td>
        <td>${escapeHtml(it.source)}</td>
        <td>${escapeHtml(it.created_at)}</td>
        <td>${escapeHtml(it.label)}</td>
        <td>${escapeHtml(it.num_cells)}</td>
        <td>${escapeHtml(it.num_locked)}</td>
        <td>${escapeHtml(it.total_hours)}</td>
        <td>${it.objective === null || it.objective === undefined ? "" : escapeHtml(Number(it.objective).toFixed(4))}</td>
        <td><button class="restore secondary" data-iteration="${escapeHtml(it.iteration)}">Restore</button></td>
      </tr>`).join("");
    el(resultId).innerHTML =
      (body.unsaved_tweaks
        ? `<p class="status-warn">The working assignment has hand-edits not yet in any iteration. `
          + `Solving saves them first; restoring something now would discard them.</p>`
        : "") +
      `<table><thead><tr><th>#</th><th>source</th><th>when</th><th>label</th>`
      + `<th>cells</th><th>locked</th><th>hours</th><th>objective</th><th></th></tr></thead>`
      + `<tbody>${rows}</tbody></table>`;

    for (const button of el(resultId).querySelectorAll("button.restore")) {
      button.addEventListener("click", () => restoreIteration(button.dataset.iteration));
    }
  } catch (err) {
    showError(resultId, err);
  }
}

async function restoreIteration(iteration) {
  const resultId = "result-history";
  busy(resultId, `Restoring iteration ${iteration}…`);
  try {
    const body = await apiCall(
      `/api/working-assignment/restore?iteration=${encodeURIComponent(iteration)}`, { method: "POST" });
    el(resultId).innerHTML =
      `<p class="status-ok">Restored iteration ${body.restored_from} — ${body.num_cells} cell(s), `
      + `${body.num_locked} locked, saved as iteration ${body.iteration}.</p>`;
    refreshState();
    loadHistory();
  } catch (err) {
    showError(resultId, err);
  }
}

el("btn-history").addEventListener("click", loadHistory);

// --- 5. Export work assignments (commit) ----------------------------------------

async function exportAssignments(force) {
  const resultId = "result-export";
  busy(resultId, "Committing…");
  try {
    const body = await apiCall(`/api/export-work-assignments?force=${String(force)}`, { method: "POST" });
    el(resultId).innerHTML =
      `<p class="status-ok">Committed ${body.num_assignments} assignment(s) for ${body.month}`
      + (body.forced ? ` <span class="status-warn">(forced — not solved since the last tweak)</span>` : "")
      + `.</p>` +
      renderTable(body.rows, ["worker_name", "project_name", "month", "hours_assigned"]);
    refreshState();
    loadHistory();
  } catch (err) {
    if (err.status === 409 && !force) {
      el(resultId).innerHTML =
        `<p class="status-warn">${escapeHtml(err.message)}</p>` +
        `<button id="btn-export-force">Commit anyway</button>`;
      el("btn-export-force").addEventListener("click", () => exportAssignments(true));
      return;
    }
    showError(resultId, err);
  }
}

el("btn-export").addEventListener("click", () => exportAssignments(false));

// --- 6. Bounds-shaped pre-assignments -------------------------------------------

el("btn-upload-pre-assignments").addEventListener("click", async () => {
  const fileInput = el("pre-assignment-file");
  const resultId = "result-pre-assignments";
  if (!fileInput.files.length) {
    el(resultId).innerHTML = `<p class="status-warn">Choose a JSON file first.</p>`;
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  try {
    const body = await apiCall("/api/pre-assignments/upload", { method: "POST", body: formData });
    el(resultId).innerHTML = `<p class="status-ok">Loaded ${body.loaded} pre-assignment row(s).</p>`;
    refreshState();
  } catch (err) {
    showError(resultId, err);
  }
});

// --- 7. Portfolio reports --------------------------------------------------------

el("btn-portfolio").addEventListener("click", async () => {
  const resultId = "result-portfolio";
  busy(resultId, "Generating reports…");
  try {
    const body = await apiCall("/api/run-portfolio-reports", { method: "POST" });
    el(resultId).innerHTML =
      `<p class="status-ok">${body.num_active_projects} active project(s) as of ${body.month}.</p>` +
      `<h3>Budget summary</h3>` +
      renderTable(body.budget_rows, [
        "project_name", "month", "planned_spend", "actual_spend", "delta",
        "cumulative_planned_spend", "cumulative_actual_spend", "planned_funds_remaining", "actual_funds_remaining",
      ]) +
      `<h3>Staffing balance</h3>` +
      renderTable(body.balance_rows, ["month", "capacity_dollars", "demand_dollars", "balance_dollars", "status"]);
  } catch (err) {
    showError(resultId, err);
  }
});

// --- 8. Actuals & close the month ------------------------------------------------

async function submitActuals(dryRun) {
  const resultId = "result-actuals";
  const fileInput = el("actuals-file");
  const acceptReforecast = el("accept-reforecast").checked;
  const formData = new FormData();
  if (fileInput.files.length) {
    formData.append("file", fileInput.files[0]);
  } else {
    // No real actuals file yet: send an empty CSV with just a header, so the
    // backend falls back to synthetic actuals (io/synthetic.py) — lets the
    // tutorial be walked through before a real timekeeping export exists.
    formData.append("file", new Blob(["person_id,project_id,hours_actual\n"], { type: "text/csv" }), "empty.csv");
  }
  const params = new URLSearchParams({ dry_run: String(dryRun), accept_reforecast: String(acceptReforecast) });
  busy(resultId, "Working…");
  try {
    const body = await apiCall(`/api/actuals/upload?${params}`, { method: "POST", body: formData });
    if (dryRun) {
      const proposalsText = body.proposals.length
        ? body.proposals.map((p) => `${p.project_id}: variance ${p.variance.toFixed(0)}`).join("; ")
        : "No reforecast proposals.";
      el(resultId).innerHTML =
        `<p><strong>Preview for ${body.month}</strong> — not saved yet.</p>` +
        `<p>${escapeHtml(proposalsText)}</p>` +
        renderTable(body.variance_rows, ["worker_name", "project_name", "hours_assigned", "actual_hours", "delta"]);
    } else {
      el(resultId).innerHTML =
        `<p class="status-ok">Closed ${body.month}. Reforecast applied: ${body.reforecast_applied}.</p>` +
        renderTable(body.variance_rows, ["worker_name", "project_name", "hours_assigned", "actual_hours", "delta"]);
      refreshState();
    }
  } catch (err) {
    showError(resultId, err);
  }
}

el("btn-actuals-preview").addEventListener("click", () => submitActuals(true));
el("btn-actuals-commit").addEventListener("click", () => submitActuals(false));

// --- 9. Variance report ----------------------------------------------------------

el("btn-variance").addEventListener("click", async () => {
  const resultId = "result-variance";
  const month = el("variance-month").value.trim();
  if (!month) {
    el(resultId).innerHTML = `<p class="status-warn">Enter a month, e.g. 2027-01.</p>`;
    return;
  }
  try {
    const body = await apiCall(`/api/reports/variance?month=${encodeURIComponent(month)}`);
    el(resultId).innerHTML = renderTable(body.rows, ["worker_name", "project_name", "hours_assigned", "actual_hours", "delta"]);
  } catch (err) {
    showError(resultId, err);
  }
});

refreshState();
loadHistory();
