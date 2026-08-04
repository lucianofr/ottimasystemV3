# Contexto de build: raiz do repositório (o pyproject.toml/uv.lock do workspace são
# necessários para resolver o pacote opcsim).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
COPY tests ./tests
RUN uv sync --frozen --package opcsim

FROM python:3.12-slim-bookworm
WORKDIR /app
RUN useradd --create-home ottima
COPY --from=builder /app /app
RUN chown -R ottima:ottima /app
ENV PATH="/app/.venv/bin:$PATH"
USER ottima
EXPOSE 4840
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 4840), timeout=2).close()"
CMD ["python", "-m", "opcsim", "--host", "0.0.0.0", "--port", "4840", "--security", "basic256sha256"]
