# Single image for all three processes; the compose command selects the entrypoint.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY sentinel_vantage ./sentinel_vantage
RUN pip install --upgrade pip && pip install .

# Default command is the MCP server; overridden per service in docker-compose.
CMD ["sv-mcp"]
