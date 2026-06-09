FROM python:3.12-slim

WORKDIR /app

# System deps: curl (healthcheck), gcc (some native wheels)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from pyproject.toml (layer cached until it changes)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "mcp[cli]" httpx pypdf pillow boto3 \
    google-api-python-client google-auth google-auth-oauthlib

# Copy source
COPY . .

# Default env — override via docker-compose or -e flags
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_READ_ONLY=1 \
    MCP_THREAD_LIMIT=120

EXPOSE 8000

# TCP-level health check — works without a dedicated /health route
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import socket; s=socket.create_connection(('127.0.0.1',8000),3); s.close()"

CMD ["python", "server.py"]
