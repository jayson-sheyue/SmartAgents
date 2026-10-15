# Feishu MCP (Cloud Run) — embeds lark-cli for bot OpenAPI calls

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @larksuite/cli@latest \
    && lark-cli --version \
    && (command -v lark-cli >/dev/null || ls "$(npm root -g)/@larksuite/cli" >/dev/null) \
    && rm -rf /var/lib/apt/lists/*

COPY services/feishu_mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY domains /app/domains
COPY mcp_server /app/mcp_server
COPY smart_agents/env_runtime.py /app/smart_agents/env_runtime.py
COPY smart_agents/__init__.py /app/smart_agents/__init__.py

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV MCP_DISABLE_DNS_REBINDING=1
ENV MCP_STATELESS_HTTP=1
ENV FASTMCP_STATELESS_HTTP=true
ENV FASTMCP_JSON_RESPONSE=true
ENV PATH="/usr/local/bin:${PATH}"

EXPOSE 8080
CMD ["python", "mcp_server/feishu_mcp.py", "--http"]
