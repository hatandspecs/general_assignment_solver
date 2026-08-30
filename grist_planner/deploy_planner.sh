#!/usr/bin/env bash
# Deploys the Grist-based planner UI: Grist itself, the planner-api backend that
# wraps allocsolver, and (on first `up`) provisions the document schema, the
# control-panel widget page, and the tutorial's starting dataset.
#
# Usage: ./deploy_planner.sh up|down|reset|logs|status|seed

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=.env

ensure_env_file() {
    if [ -f "$ENV_FILE" ]; then
        return
    fi
    echo "No $ENV_FILE found — creating one from .env.example with a fresh boot key."
    cp .env.example "$ENV_FILE"
    local boot_key
    boot_key=$(python3 -c "import secrets; print(secrets.token_hex(16))")
    # macOS/BSD sed needs -i '', GNU sed needs -i — this form works on both.
    sed -i.bak "s/^GRIST_BOOT_KEY=.*/GRIST_BOOT_KEY=${boot_key}/" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
}

port_from_env() {
    # $1: var name, $2: default
    grep "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || echo "$2"
}

cmd_up() {
    ensure_env_file
    docker compose up -d --build
    echo
    echo "Waiting for Grist and provisioning the document (tables, widget page, tutorial data)..."
    docker compose run --rm planner-api python -m planner_api.provisioning --seed-dir /tutorial_data/data

    local grist_port planner_port
    grist_port=$(port_from_env GRIST_PORT 8484)
    planner_port=$(port_from_env PLANNER_API_PORT 8000)
    echo
    echo "Up. Open the planner in Grist at:"
    echo "    http://localhost:${grist_port}"
    echo "(the control-panel widget is already embedded on its own page inside the doc)"
    echo
    echo "Backend API directly at http://localhost:${planner_port} (see /health)."
}

cmd_down() {
    docker compose down
}

cmd_reset() {
    echo "This deletes the Grist document and all planner state (the containers and volumes)."
    read -r -p "Type 'yes' to continue: " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted."
        exit 1
    fi
    docker compose down -v
    rm -f "$ENV_FILE"
    echo "Reset. Run 'up' again to provision a fresh document."
}

cmd_logs() {
    docker compose logs -f "$@"
}

cmd_status() {
    docker compose ps
}

cmd_seed() {
    # Re-runs only the seeding step, e.g. after `reset` or against a doc that was
    # provisioned without --seed-dir. Safe to re-run: seed_from_local_data skips
    # if the Meta table already has a plan in it.
    docker compose run --rm planner-api python -m planner_api.provisioning --seed-dir /tutorial_data/data
}

case "${1:-}" in
    up) cmd_up ;;
    down) cmd_down ;;
    reset) cmd_reset ;;
    logs) shift; cmd_logs "$@" ;;
    status) cmd_status ;;
    seed) cmd_seed ;;
    *)
        echo "Usage: $0 up|down|reset|logs|status|seed"
        exit 1
        ;;
esac
