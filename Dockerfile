FROM python:3.12-slim AS runtime

# Runtime system deps (SPADE/XMPP + build tools for wheels if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Env defaults (overridden in docker-compose)
ENV PYTHONPATH=/app \
    MONGODB_URI=mongodb://mongo:27017 \
    REDIS_URL=redis://redis:6379/0

EXPOSE 8000
