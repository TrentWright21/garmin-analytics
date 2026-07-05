# ---- Stage 1: build the React dashboard ------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python API serving the built dashboard ------------------------
FROM python:3.12-slim

# Layout mirrors a source checkout so REPO_ROOT (backend/app/config.py's
# parents[2] = /srv) resolves the same relative paths as on a laptop:
#   /srv/backend/app  /srv/frontend/dist  /srv/config  /srv/data
WORKDIR /srv/backend

# Install dependencies first for layer caching (app source copied below).
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/app ./app
COPY config /srv/config
COPY --from=frontend /build/dist /srv/frontend/dist

# Non-root user; /srv/data is volume-mounted by compose.
RUN useradd -m runner && mkdir -p /srv/data && chown -R runner /srv
USER runner

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
