FROM python:3.14-slim-bookworm

# Install system dependencies: ffmpeg for media processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files and install (includes yt-dlp Python library)
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir . yt-dlp

# Create output data directory and non-root user
RUN mkdir -p /data && \
    addgroup --system mcp && adduser --system --ingroup mcp mcp && \
    chown -R mcp:mcp /data

USER mcp

ENV PYTHONUNBUFFERED=1
ENV TRANSPORT=http
ENV HOST=0.0.0.0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request,json,sys; r=urllib.request.urlopen('http://localhost:8000/health',timeout=3); d=json.loads(r.read()); sys.exit(0 if d.get('status')=='healthy' else 1)"

CMD ["mcp-ytdlp"]
