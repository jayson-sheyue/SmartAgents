# Etsy MCP (Cloud Run) — reviews + sync scene-swap (Vertex)

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY services/etsy_mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY domains /app/domains
COPY mcp_server /app/mcp_server
COPY smart_agents/env_runtime.py /app/smart_agents/env_runtime.py
COPY smart_agents/__init__.py /app/smart_agents/__init__.py

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV MCP_DISABLE_DNS_REBINDING=1

EXPOSE 8080
CMD ["python", "mcp_server/etsy_mcp.py", "--http"]
