"""Thin Grist REST API wrapper — `docs/05-interfaces.md`'s `GristClient` contract,
extended pragmatically for this deployment (the doc's original three-method
sketch assumed a hand-run pull/solve/push cycle; this adds what a live, button-
driven UI needs: table creation, generic useractions, and full-table read/write).

Two layers:

- Module-level functions (`boot_login`, `get_or_create_api_key`, `ensure_workspace`,
  `ensure_doc`) — bootstrap-only, used once by `provisioning.py` to go from a bare
  Grist instance to a doc with a real API key, via the boot-key admin login flow
  (`Boot.js`'s documented `/boot/verify-boot-key` + `/boot/login`).
- `GristClient` — everything the running service needs afterward, authenticated
  by that API key. `docs/06-code-structure-and-dependencies.md` names `httpx` as
  the intended dependency for exactly this.
"""

from __future__ import annotations

import httpx


def boot_login(base_url: str, boot_key: str, admin_email: str) -> httpx.Client:
    """One-time admin login via the operator-only boot key. Returns a session
    (cookie-authenticated) client — used only to mint a real API key, never held
    onto afterward."""
    session = httpx.Client(base_url=base_url, timeout=30.0)
    resp = session.post("/boot/verify-boot-key", json={"bootKey": boot_key})
    resp.raise_for_status()
    resp = session.post("/boot/login", json={"bootKey": boot_key, "adminEmail": admin_email})
    resp.raise_for_status()
    return session


def get_or_create_api_key(session: httpx.Client) -> str:
    """GET returns the admin's existing key if one was already minted (by a prior
    provisioning run); POST mints one the first time. Never re-POSTs once a key
    exists — Grist rejects a second POST unless `force: true`, which would
    invalidate the key the running backend already has on file."""
    headers = {"X-Requested-With": "XMLHttpRequest"}
    resp = session.get("/api/profile/apikey", headers=headers)
    resp.raise_for_status()
    key = resp.text.strip().strip('"')
    if key:
        return key
    resp = session.post("/api/profile/apikey", json={}, headers=headers)
    resp.raise_for_status()
    return resp.text.strip().strip('"')


def ensure_workspace(session: httpx.Client, workspace_name: str) -> tuple[str, int]:
    """Returns (org_domain, workspace_id). The admin's personal org already exists
    right after boot-login — no org-creation step needed."""
    orgs = session.get("/api/orgs").json()
    org_domain = orgs[0]["domain"]

    workspaces = session.get(f"/api/orgs/{org_domain}/workspaces").json()
    existing = next((w for w in workspaces if w["name"] == workspace_name), None)
    if existing is not None:
        return org_domain, existing["id"]

    resp = session.post(
        f"/api/orgs/{org_domain}/workspaces",
        json={"name": workspace_name},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return org_domain, resp.json()


def grant_anonymous_access(session: httpx.Client, org_domain: str) -> None:
    """Grants the special `anon@getgrist.com` user "editors" access on the org —
    the actual fix for needing to log into Grist at all. `GRIST_IN_SERVICE=true`
    (Grist's own documented "turn off this check" env var) only lifts the
    operator-verification wall in front of `/boot`; it does *not* grant an
    anonymous browser session access to a document owned by a real logged-in
    user's personal org, which is what provisioning creates — confirmed by
    driving a real (Playwright) browser against a document shared this way vs.
    not: without this grant, a fresh anonymous session gets "Access denied" even
    with `GRIST_IN_SERVICE=true` set; with it, the same session opens and edits
    the doc immediately, no boot key or sign-in ever shown. This is exactly the
    "local-only, no auth" posture `docs/08-grist-ui-design.md` already commits
    to — this just makes it apply to the planner's own browser too, not only to
    `planner-api`'s server-side API calls.
    """
    resp = session.patch(
        f"/api/orgs/{org_domain}/access",
        json={"delta": {"users": {"anon@getgrist.com": "editors"}}},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()


def ensure_doc(session: httpx.Client, workspace_id: int, doc_name: str) -> str:
    """Returns the doc id, creating the doc (and removing its default `Table1`) if
    it doesn't already exist by name."""
    workspace = session.get(f"/api/workspaces/{workspace_id}").json()
    existing = next((d for d in workspace.get("docs", []) if d["name"] == doc_name), None)
    if existing is not None:
        return existing["id"]

    resp = session.post(
        f"/api/workspaces/{workspace_id}/docs",
        json={"name": doc_name},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    doc_id = resp.json().strip('"')

    resp = session.post(f"/api/docs/{doc_id}/apply", json=[["RemoveTable", "Table1"]])
    resp.raise_for_status()
    return doc_id


class GristClient:
    """Authenticated by a real API key (post-provisioning) — what `main.py`'s
    endpoints use on every request."""

    def __init__(self, base_url: str, api_key: str, doc_id: str):
        self.doc_id = doc_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    def grant_anonymous_access(self, org_domain: str) -> None:
        """Same grant as the module-level `grant_anonymous_access`, callable with
        this client's own API-key auth — used to backfill the grant onto a doc
        that was already provisioned before this existed."""
        resp = self._client.patch(
            f"/api/orgs/{org_domain}/access", json={"delta": {"users": {"anon@getgrist.com": "editors"}}}
        )
        resp.raise_for_status()

    def list_tables(self) -> list[str]:
        resp = self._client.get(f"/api/docs/{self.doc_id}/tables")
        resp.raise_for_status()
        return [t["id"] for t in resp.json()["tables"]]

    def create_table(self, table_id: str, columns: list[tuple[str, str]]) -> None:
        payload = {
            "tables": [
                {
                    "id": table_id,
                    "columns": [{"id": col_id, "fields": {"label": col_id, "type": col_type}} for col_id, col_type in columns],
                }
            ]
        }
        resp = self._client.post(f"/api/docs/{self.doc_id}/tables", json=payload)
        resp.raise_for_status()

    def apply_actions(self, actions: list) -> dict:
        resp = self._client.post(f"/api/docs/{self.doc_id}/apply", json=actions)
        resp.raise_for_status()
        return resp.json()

    def fetch_records(self, table_id: str) -> list[dict]:
        """Each record comes back as `{"id": <grist row id>, **fields}` — the row
        id is needed for `delete_records`/`replace_table`, not part of the model."""
        resp = self._client.get(f"/api/docs/{self.doc_id}/tables/{table_id}/records")
        resp.raise_for_status()
        return [{"id": r["id"], **r["fields"]} for r in resp.json()["records"]]

    def add_records(self, table_id: str, records: list[dict]) -> list[int]:
        if not records:
            return []
        payload = {"records": [{"fields": r} for r in records]}
        resp = self._client.post(f"/api/docs/{self.doc_id}/tables/{table_id}/records", json=payload)
        resp.raise_for_status()
        return [r["id"] for r in resp.json()["records"]]

    def delete_records(self, table_id: str, row_ids: list[int]) -> None:
        if not row_ids:
            return
        self.apply_actions([["BulkRemoveRecord", table_id, row_ids]])

    def replace_table(self, table_id: str, records: list[dict]) -> None:
        """Wholesale overwrite — mirrors `io/local.py`'s `save_plan`, which
        rewrites each JSON file in full rather than patching it incrementally."""
        existing_ids = [r["id"] for r in self.fetch_records(table_id)]
        self.delete_records(table_id, existing_ids)
        self.add_records(table_id, records)

    def create_custom_widget_page(self, bind_table_id: str, widget_url: str, page_title: str) -> int:
        """Adds a new page with a single custom-widget section pointed at
        `widget_url`. `bind_table_id` just gives the section something to attach
        to and is not otherwise used by this widget (it talks to its own backend,
        never `grist.docApi` — see `docs/08-grist-ui-design.md`, "Why the widget
        doesn't talk to Grist directly" — so `access: "none"` is correct and is
        also Grist's own default; there's no elevated permission to grant).

        Reverse-engineered from a real "Add widget to page" flow (driven with
        Playwright against a live container, since this is unverifiable from
        source reading alone) — two details that reading `ViewSectionRec.js` in
        isolation got wrong:

        1. `CreateViewSection`'s first argument must be the *existing* table's
           real ref, not `0` — passing `0` (meant to mean "no table yet") along
           with a `tableId` string is read as "create a *new* table with this
           name hint", which silently creates a duplicate (e.g. `People2`)
           instead of attaching to the real `People` table.
        2. `_grist_Views_section.options` is a JSON-string column whose
           `customView` *property* is itself a JSON-encoded **string**, not a
           nested object — `ViewSectionRec.js` parses it as a string
           (`jsonObservable(optionsObj.prop("customView"), ...)`); storing a real
           nested object there (as an earlier version of this method did) means
           that inner parse fails, and the widget frame throws trying to read
           properties (`mode`, `sectionId`, ...) off the resulting `undefined` —
           exactly the "Cannot read properties of undefined" error this fixes.
        """
        tables_meta = self.fetch_records("_grist_Tables")
        table_ref = next((r["id"] for r in tables_meta if r["tableId"] == bind_table_id), None)
        if table_ref is None:
            raise ValueError(f"create_custom_widget_page: no such table {bind_table_id!r}")

        result = self.apply_actions([["CreateViewSection", table_ref, 0, "custom", None, None]])
        ret = result["retValues"][0]
        section_ref, view_ref = ret["sectionRef"], ret["viewRef"]
        import json as _json

        custom_view = _json.dumps(
            {
                "mode": "url",
                "url": widget_url,
                "widgetDef": None,
                "access": "none",
                "pluginId": "",
                "sectionId": "",
                "renderAfterReady": False,
                "widgetId": None,
                "widgetOptions": None,
                "columnsMapping": None,
            }
        )
        options = _json.dumps(
            {
                "verticalGridlines": True,
                "horizontalGridlines": True,
                "zebraStripes": False,
                "rowNumbers": "number",
                "customView": custom_view,
                "numFrozen": 0,
            }
        )
        self.apply_actions(
            [
                ["UpdateRecord", "_grist_Views_section", section_ref, {"options": options}],
                ["UpdateRecord", "_grist_Views", view_ref, {"name": page_title}],
            ]
        )
        return section_ref
