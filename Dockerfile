FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "municipal_finances.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
