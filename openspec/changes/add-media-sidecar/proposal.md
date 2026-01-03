# Change: Add Media Processing Sidecar Service

## Why
n8n workflows need to download videos from various sources (YouTube, etc.) and extract screenshots/frames from those videos. Rather than extending the n8n Docker image with heavy video processing tools (yt-dlp, ffmpeg), a sidecar microservice approach provides better isolation, stability, and maintainability. This keeps the n8n instance clean and prevents CPU-intensive video processing from impacting workflow orchestration.

## What Changes
- Add a Python FastMCP microservice container that provides MCP (Model Context Protocol) tools for video download, conversion, screenshot extraction, and manual cleanup
- Implement video download capability using yt-dlp with MP4 format optimization and optional cookies file support for authentication
- Implement video conversion/transcoding capability using ffmpeg for format conversion
- Implement screenshot extraction capability using ffmpeg at specified timestamps
- Implement automatic cleanup of video files with configurable retention period (default 7 days) based on file creation date
- Implement manual cleanup MCP tool for on-demand cleanup operations
- Implement progress tracking for long-running operations (downloads, conversions)
- Add environment variable configuration for output directory, retention period, and filename formats
- Configure Docker Compose to run the sidecar alongside n8n with shared volume access and HTTP transport on port 8000 for network-based MCP client access
- Establish shared storage volume (`/mnt/data/AI/n8n:/data`) between n8n and media-sidecar containers for file exchange, reusing existing n8n volume configuration

## Impact
- Affected specs: New `media-processing` capability
- Affected code:
  - New `main.py` (FastMCP server application)
  - New `Dockerfile` (media-sidecar container)
  - New/updated `docker-compose.yml` (sidecar service configuration)
  - New `requirements.txt` (Python dependencies: fastmcp, yt-dlp)
  - New `README.md` (comprehensive setup and usage documentation with quick start, configuration, MCP tool reference, and troubleshooting)
- Integration: LLMs and AI assistants can directly interact with the service via MCP protocol. n8n can access via MCP client or continue using shared volume file access.

