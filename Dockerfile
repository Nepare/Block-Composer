FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY config.yaml ./
COPY input_prompts/ input_prompts/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["cvdocs-web"]
