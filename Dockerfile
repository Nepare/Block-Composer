FROM oven/bun:1 AS frontend-builder

WORKDIR /app/frontend

COPY frontend/ ./

RUN bun install --frozen-lockfile && bun run build

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY config.yaml ./
COPY templates.yaml ./
COPY input_prompts/ input_prompts/

RUN pip install --no-cache-dir .

COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["cvdocs-web"]
