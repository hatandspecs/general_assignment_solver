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

function renderTable(rows, columns) {
  if (!rows || rows.length === 0) return "<p><em>No rows.</em></p>";
  const header = columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${columns.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function apiCall(path, options) {
  const resp = await fetch(path, options);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = body.detail || resp.statusText;
    throw new Error(`${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return body;
}

function showError(resultId, err) {
  el(resultId).innerHTML = `<p class="status-err">Error: ${escapeHtml(err.message || err)}</p>`;
}

async function refreshState() {
  const banner = el("state-banner");
  try {
    const state = await apiCall("/api/state");
    banner.classList.remove("error");
    banner.textContent = state.horizon_exhausted
      ? `Horizon complete (${state.horizon_start} to ${state.horizon_end}).`
      : `Current month to plan: ${state.current_month} `
        + `(horizon ${state.horizon_start}–${state.horizon_end}, closed through ${state.closed_through || "nothing yet"}). `
        + `${state.num_pre_assignments} pre-assignment(s) pending.`;
  } catch (err) {
    banner.classList.add("error");
    banner.textContent = `Couldn't load plan state: ${err.message}`;
  }
}

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

el("btn-run-planning").addEventListener("click", async () => {
  const resultId = "result-run-planning";
  el(resultId).innerHTML = "<p>Solving…</p>";
  try {
    const body = await apiCall("/api/run-planning", { method: "POST" });
    const countsText = Object.entries(body.diff_counts)
      .map(([status, count]) => `${status}: ${count}`)
      .join(", ");
    el(resultId).innerHTML =
      `<p class="status-ok">Feasible for ${body.month}. Objective: ${body.objective?.toFixed(3) ?? "n/a"}.</p>` +
      `<p>${countsText || "No pre-assignments or solved cells this month."}</p>` +
      renderTable(body.diff_rows, ["project_id", "person_id", "pre_assigned_hours", "solved_hours", "delta", "status"]);
  } catch (err) {
    showError(resultId, err);
  }
});

el("btn-export").addEventListener("click", async () => {
  const resultId = "result-export";
  el(resultId).innerHTML = "<p>Solving and committing…</p>";
  try {
    const body = await apiCall("/api/export-work-assignments", { method: "POST" });
    el(resultId).innerHTML =
      `<p class="status-ok">Committed. ${body.num_assignments} assignment row(s) for ${body.month}.</p>` +
      renderTable(body.rows, ["worker_name", "project_name", "month", "hours_assigned"]);
    refreshState();
  } catch (err) {
    showError(resultId, err);
  }
});

el("btn-portfolio").addEventListener("click", async () => {
  const resultId = "result-portfolio";
  el(resultId).innerHTML = "<p>Generating reports…</p>";
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
  el(resultId).innerHTML = "<p>Working…</p>";
  try {
    const body = await apiCall(`/api/actuals/upload?${params}`, { method: "POST", body: formData });
    if (dryRun) {
      const proposalsText = body.proposals.length
        ? body.proposals.map((p) => `${p.project_id}: variance ${p.variance.toFixed(0)}`).join("; ")
        : "No reforecast proposals.";
      el(resultId).innerHTML =
        `<p><strong>Preview for ${body.month}</strong> — not saved yet.</p>` +
        `<p>${proposalsText}</p>` +
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
