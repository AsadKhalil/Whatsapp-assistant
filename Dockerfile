FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV PATH="/srv/.venv/bin:$PATH"
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY app ./app
EXPOSE 8000
CMD ["/srv/.venv/bin/uvicorn", "app.main:create_app", "--factory", "--no-access-log", "--host", "0.0.0.0", "--port", "8000"]
