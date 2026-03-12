FROM python:3.12-slim-bookworm

# Install system dependencies: ffmpeg for media processing, yt-dlp CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install from PyPI (includes yt-dlp Python library)
RUN pip install --no-cache-dir mcp-ytdlp yt-dlp

# Create output data directory
RUN mkdir -p /data

EXPOSE 8000

CMD ["mcp-ytdlp"]
