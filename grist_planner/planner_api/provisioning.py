"""One-time (idempotent) setup: turns a bare Grist instance into a doc with the
full Plan schema, the Pre-Assignments and Report tables, and a page embedding the
control-panel widget — then, optionally, seeds it from a local JSON data
directory shaped like `allocsolver/io/local.py`'s files (used for the tutorial's
starting dataset).

Run via `docker compose run --rm planner-api python -m planner_api.provisioning`
(that's what `deploy_planner.sh up` does) — safe to re-run: it reuses the existing
API key/doc if `STATE_FILE` already names one, and only adds tables that are
missing, rather than starting over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from allocsolver.io.local import load_plan

from .grist_client import GristClient, boot_login, ensure_doc, ensure_workspace, get_or_create_api_key
from .plan_sync import save_plan_to_grist
from .schema import ALL_TABLES

STATE_FILE = Path(os.environ.get("STATE_FILE", "/data/.grist_state.json"))


def _wait_for_grist(base_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/status", timeout=5.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Grist never became ready at {base_url}") from last_error


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _ensure_tables(client: GristClient) -> None:
    existing = set(client.list_tables())
    for table in ALL_TABLES:
        if table.table_id in existing:
            continue
        print(f"  creating table {table.table_id}")
        client.create_table(table.table_id, table.columns)


def provision(
    internal_grist_url: str,
    boot_key: str,
    admin_email: str,
    workspace_name: str,
    doc_name: str,
    widget_url: str,
) -> GristClient:
    """Returns a ready-to-use `GristClient` for the provisioned doc."""
    _wait_for_grist(internal_grist_url)

    state = _load_state()
    if state is not None:
        print(f"Reusing existing provisioning state at {STATE_FILE}")
        client = GristClient(internal_grist_url, state["api_key"], state["doc_id"])
        try:
            _ensure_tables(client)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Stale state file at {STATE_FILE} doesn't match a working Grist doc "
                f"({exc}). Delete it and re-run to provision fresh."
            ) from exc
        return client

    print("No existing state found — provisioning a new document.")
    session = boot_login(internal_grist_url, boot_key, admin_email)
    api_key = get_or_create_api_key(session)
    org_domain, workspace_id = ensure_workspace(session, workspace_name)
    doc_id = ensure_doc(session, workspace_id, doc_name)
    session.close()

    client = GristClient(internal_grist_url, api_key, doc_id)
    print(f"Doc created: org={org_domain} workspace_id={workspace_id} doc_id={doc_id}")

    _ensure_tables(client)

    print(f"Adding the control-panel widget page, pointed at {widget_url}")
    client.create_custom_widget_page("People", widget_url, "Planner Control Panel")

    _save_state(
        {
            "org_domain": org_domain,
            "workspace_id": workspace_id,
            "doc_id": doc_id,
            "api_key": api_key,
        }
    )
    return client


def seed_from_local_data(client: GristClient, data_dir: Path) -> None:
    """Loads a Plan from a local JSON data directory (`io/local.py`'s layout) and
    writes it into the provisioned doc — skipped if the Meta table already has a
    row, so re-running `deploy_planner.sh up` never clobbers in-progress planner work."""
    if client.fetch_records("Meta"):
        print("Meta table already populated — skipping seed (doc already has a plan).")
        return
    print(f"Seeding starting data from {data_dir}")
    plan = load_plan(data_dir)
    save_plan_to_grist(plan, client)
    print(f"Seeded {len(plan.people)} people, {len(plan.projects)} projects.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-dir", type=Path, default=None, help="Local JSON data dir to seed the doc from")
    args = parser.parse_args()

    internal_grist_url = os.environ["GRIST_INTERNAL_URL"]
    boot_key = os.environ["GRIST_BOOT_KEY"]
    admin_email = os.environ.get("GRIST_ADMIN_EMAIL", "planner@example.com")
    workspace_name = os.environ.get("GRIST_WORKSPACE_NAME", "Planner")
    doc_name = os.environ.get("GRIST_DOC_NAME", "Labor Allocation Planner")
    widget_url = os.environ["WIDGET_URL"]

    client = provision(internal_grist_url, boot_key, admin_email, workspace_name, doc_name, widget_url)

    if args.seed_dir is not None:
        seed_from_local_data(client, args.seed_dir)

    print(f"\nDone. Doc id: {client.doc_id}")
    print(f"Open the Grist UI at the browser-facing URL printed by deploy_planner.sh to use it.")
    client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level CLI entrypoint, want a clean message
        print(f"Provisioning failed: {exc}", file=sys.stderr)
        sys.exit(1)
