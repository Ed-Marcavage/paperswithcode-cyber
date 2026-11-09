FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS backend
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.21
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY backend ./backend
COPY url_extraction_agent ./url_extraction_agent
COPY latex_compiler_contract ./latex_compiler_contract
COPY latex_compiler_space ./latex_compiler_space
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
CMD ["node", "node_modules/vite/bin/vite.js", "--config", "vite.local.config.ts"]
