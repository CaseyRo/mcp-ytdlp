FROM python:3.12-slim-bookworm

# Install system dependencies: ffmpeg for media processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files and install (includes yt-dlp Python library)
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir . yt-dlp

# Create output data directory
RUN mkdir -p /data

EXPOSE 8000

CMD ["mcp-ytdlp"]
