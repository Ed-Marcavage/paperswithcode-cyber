FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
RUN apt-get update && apt-get install -y --no-install-recommends patch && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.9.21
WORKDIR /src
COPY --from=pwc_cli standalone_cli standalone_cli
COPY --from=pwc_cli mcp_server mcp_server
COPY mcp.patch /tmp/mcp.patch
COPY mcp_analytics.py mcp_server/src/pwc_mcp/mcp_analytics.py
RUN patch -p1 < /tmp/mcp.patch && uv sync --project mcp_server --frozen --no-dev --no-editable
ENV PWC_MCP_HOST=0.0.0.0 PORT=7860
USER nobody
CMD ["/src/mcp_server/.venv/bin/pwc-mcp"]
