# Grist Planner UI

A self-hosted [Grist](https://www.getgrist.com/) document, backed by a small
FastAPI service (`planner_api/`) that wraps the `allocsolver` package, with a
control-panel widget (`widget/`) embedded in the document itself. See
`docs/08-grist-ui-design.md` for the full design and `docs/09-planner-tutorial.md`
for a walkthrough.

## Quickstart

Requires Docker and Docker Compose.

```bash
./deploy_planner.sh up
```

First run generates `.env` (a random Grist admin boot key), builds the backend
image, starts both containers, and provisions a fresh document with the full
schema, the widget page, and `examples/small_example/data/`. Takes under a
minute. `up`'s own output then prints a **one-time** step: your browser needs to
log into Grist once (the provisioning script logs in server-side, which isn't
the same as your browser having a session) — after that you stay logged in
across every future `up`/`down`. Then open **http://localhost:8484**.

## Commands

```bash
./deploy_planner.sh up       # start (or resume) the stack; idempotent
./deploy_planner.sh down     # stop containers, keep all data
./deploy_planner.sh reset    # destroy everything (containers, volumes, .env) — confirms first
./deploy_planner.sh logs     # follow both containers' logs
./deploy_planner.sh status   # docker compose ps
./deploy_planner.sh seed     # re-run just the data-seed step

# Any of up/seed also take --example, to seed examples/medium_example instead
# of the default examples/small_example (needs `reset` first if already seeded):
./deploy_planner.sh up --example medium_example
```

## Layout

```
deploy_planner.sh       the one command you run
docker-compose.yml       mounts ../examples read-only, for seeding
docker/Dockerfile        planner-api's image (installs allocsolver + this service)
planner_api/
    main.py                 FastAPI endpoints — what the widget's buttons call
    grist_client.py          REST wrapper: boot-key login, api key, tables, records
    plan_sync.py              Plan <-> Grist tables (mirrors allocsolver/io/local.py)
    provisioning.py            idempotent one-time setup, run via `docker compose run`
    reports.py                 report-row computation for the widget's report buttons
    schema.py                   the Grist table schema, single source of truth
widget/                  the control-panel widget: index.html, widget.js, widget.css
```

The dataset seeded on `up` lives in `../examples/small_example/` (or
`../examples/medium_example/`) — see that example's own README, and
`docs/09-planner-tutorial.md` for the walkthrough.

## Local-only, by design

No TLS, no auth beyond a single admin account, CORS wide open. Built for one
planner (or a small team) on one machine or trusted network — see
`docs/08-grist-ui-design.md`'s "Auth and scope". Don't expose these ports beyond
`localhost` without adding real auth in front of both services first.
