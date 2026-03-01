# ── Stage 1: Build fpocket from source ────────────────────────────────────────
FROM python:3.12-slim AS fpocket-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    make \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch v3.2.1 https://github.com/Discngine/fpocket.git . \
    && mkdir build_cmake \
    && cd build_cmake \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
    && make -j$(nproc) \
    && make install

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Copy fpocket binary from builder
COPY --from=fpocket-builder /usr/local/bin/fpocket /usr/local/bin/fpocket

# Runtime system deps (needed by fpocket at runtime + SPADE XMPP)
RUN apt-get update && apt-get install -y --no-install-recommends \
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

# Verify fpocket is available
RUN fpocket --version || fpocket -h || echo "fpocket installed OK"

EXPOSE 8000
