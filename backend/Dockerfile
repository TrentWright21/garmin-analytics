FROM python:3.12-slim

WORKDIR /srv

# Install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app

# Non-root user; data dir is volume-mounted by compose
RUN useradd -m runner && mkdir -p /srv/data && chown -R runner /srv
USER runner

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
