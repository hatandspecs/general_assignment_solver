# Build context is the repo root (see docker-compose.yml's `context: ..`), so this
# image can install `allocsolver` itself alongside the small FastAPI service that
# wraps it — one image, reused for both the long-running API and the one-shot
# provisioning script (`docker compose run --rm planner-api python -m planner_api.provisioning`).
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY allocsolver ./allocsolver
RUN pip install --no-cache-dir -e .

COPY grist_planner/planner_api ./planner_api
RUN pip install --no-cache-dir -r planner_api/requirements.txt

COPY grist_planner/widget ./widget

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "planner_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
