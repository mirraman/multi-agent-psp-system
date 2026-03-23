# ── Stage 1: fpocket (C) — vendored tmp_fpocket
FROM debian:bookworm-slim AS fpocket-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libnetcdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/fpocket

COPY tmp_fpocket/makefile ./
COPY tmp_fpocket/src ./src
COPY tmp_fpocket/bin ./bin
COPY tmp_fpocket/obj ./obj
COPY tmp_fpocket/man ./man
COPY tmp_fpocket/headers ./headers
COPY tmp_fpocket/scripts ./scripts
COPY tmp_fpocket/plugins ./plugins

RUN make && make install && make clean

# ── Stage 2: Python runtime + app
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=fpocket-builder /usr/local/bin/fpocket /usr/local/bin/fpocket
COPY --from=fpocket-builder /usr/local/lib/ /usr/local/lib/

ENV LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONPATH=/app \
    REDIS_URL=redis://redis:6379/0

# Default image target: API
FROM runtime AS api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS celery

CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
