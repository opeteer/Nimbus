# ==============================================================================
# Stage 1: Dependency Builder (Compiles C extensions on Alpine)
# ==============================================================================
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install compilation tools for uvicorn standard C-extensions (uvloop, httptools)
RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ==============================================================================
# Stage 2: Minimal Production Runner (< 150MB target)
# ==============================================================================
FROM python:3.12-alpine AS runner

WORKDIR /app

# Install runtime dependencies: ffmpeg for yt-dlp media merging and extraction
RUN apk add --no-cache ffmpeg

# Create non-root system user and group for container security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy pre-compiled dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source code
COPY . .

# Ensure storage directory exists and has non-root write permissions
RUN mkdir -p /app/downloads && chown -R appuser:appgroup /app

USER appuser

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
