# YTDLP MCP Service

A FastMCP-based microservice for downloading videos, converting formats, and managing media files. Standalone service accessible via MCP protocol over HTTP.

## Overview

This service provides MCP (Model Context Protocol) tools for media processing operations:
- **Video Download**: Download videos from URLs using yt-dlp with optional authentication (includes video metadata and thumbnails)
- **Video Conversion**: Convert videos between formats using FFmpeg
- **File Cleanup**: Automatic and manual cleanup of old files

The service runs as a standalone Docker container, providing MCP tools for media processing operations via HTTP.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Network access for downloading videos

### Installation

1. **Copy service files** to your project directory:
   - `main.py`
   - `Dockerfile`
   - `requirements.txt`
   - `docker-compose.yaml` (or update your existing one)

2. **Update docker-compose.yaml** with your volume paths:
   ```yaml
   volumes:
     - /path/to/your/data:/data  # Update to your desired data directory
   ```

3. **Configure environment variables** (see Configuration section below)

4. **Start the service**:
   ```bash
   docker-compose up -d
   ```

5. **Verify the service is running**:
   ```bash
   docker-compose logs ytdlp-mcp
   ```

### Basic Usage

The MCP server is accessible via HTTP on port 8000. Connect your MCP client to:
- `http://ytdlp-mcp:8000` (from within Docker network)
- `http://localhost:8000` (from host machine)

## Configuration

### Environment Variables

All configuration is done via environment variables in `docker-compose.yaml`:

#### `OUTPUT_DIRECTORY`
- **Default**: `/data`
- **Description**: Directory where all downloaded videos and converted videos are saved
- **Example**:
  ```yaml
  environment:
    - OUTPUT_DIRECTORY=/mnt/storage/videos
  ```

#### `CLEANUP_RETENTION_DAYS`
- **Default**: `7`
- **Description**: Number of days to retain files before automatic cleanup removes them
- **Example**:
  ```yaml
  environment:
    - CLEANUP_RETENTION_DAYS=14
  ```

#### `VIDEO_FILENAME_FORMAT`
- **Default**: `%(id)s.%(ext)s` (uses video ID from URL, e.g., `dQw4w9WgXcQ.mp4`)
- **Description**: Filename format for downloaded videos using yt-dlp formatting syntax
- **Format Variables**: `%(title)s`, `%(id)s`, `%(ext)s`, `%(uploader)s`, `%(upload_date)s`, etc.
- **Note**: The default uses `%(id)s` which extracts the video ID from the URL (the last meaningful part)
- **Example**:
  ```yaml
  environment:
    - VIDEO_FILENAME_FORMAT=%(id)s.%(ext)s
  ```
  Or with title (limited to 100 chars):
  ```yaml
  environment:
    - VIDEO_FILENAME_FORMAT=%(title).100s.%(ext)s
  ```
  Or with uploader and ID:
  ```yaml
  environment:
    - VIDEO_FILENAME_FORMAT=%(uploader)s - %(id)s.%(ext)s
  ```

### Docker Compose Configuration

Example `docker-compose.yaml` configuration:

```yaml
services:
  ytdlp-mcp:
    build: .
    container_name: ytdlp-mcp
    restart: unless-stopped
    volumes:
      - /mnt/data/AI/n8n:/data
    environment:
      - OUTPUT_DIRECTORY=/data
      - CLEANUP_RETENTION_DAYS=7
      - VIDEO_FILENAME_FORMAT=%(id)s.%(ext)s
    ports:
      - "8000:8000"
    networks:
      - ytdlp-network

networks:
  ytdlp-network:
    driver: bridge
```

## MCP Tools Reference

### `download_video`

Downloads a video from a URL using yt-dlp.

**Parameters**:
- `url` (required, string): Video URL to download
- `cookies_file` (optional, string): Path to cookies file for authentication

**Example Request**:
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "cookies_file": "/path/to/cookies.txt"
}
```

**Example Response**:
```json
{
  "status": "success",
  "filename": "video.mp4",
  "path": "/data/video.mp4",
  "metadata": {
    "id": "dQw4w9WgXcQ",
    "title": "Video Title",
    "description": "Video description...",
    "duration": 212,
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
    "thumbnails": [
      {
        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
        "width": 120,
        "height": 90
      },
      {
        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "width": 480,
        "height": 360
      }
    ],
    "uploader": "Channel Name",
    "uploader_id": "channel_id",
    "channel": "Channel Name",
    "channel_id": "channel_id",
    "upload_date": "20230101",
    "view_count": 1234567,
    "like_count": 12345,
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  },
  "yt_dlp": {
    "yt_dlp_version": "2025.12.08",
    "latest_available_version": "2025.12.10",
    "update_available": true
  }
}
```

**Metadata Fields**:
- `id`: Video ID
- `title`: Video title
- `description`: Video description
- `duration`: Duration in seconds
- `thumbnail`: Primary thumbnail URL
- `thumbnails`: Array of thumbnail objects with different resolutions (each has `url`, `width`, `height`)
- `uploader`: Uploader/channel name
- `uploader_id`: Uploader ID
- `channel`: Channel name
- `channel_id`: Channel ID
- `upload_date`: Upload date in YYYYMMDD format
- `view_count`: View count (if available)
- `like_count`: Like count (if available)
- `webpage_url`: URL to the video page

**Version Information** (`yt_dlp` object):
- `yt_dlp_version`: Currently installed version of yt-dlp
- `latest_available_version`: Latest available version from PyPI (checked periodically)
- `update_available`: Boolean indicating if a newer version is available

**Error Response**:
```json
{
  "status": "error",
  "error": "Download failed: [error message]"
}
```

### `convert_video`

Converts a video file to a different format using FFmpeg.

**Parameters**:
- `video_filename` (required, string): Name of the video file to convert (must exist in output directory)
- `target_format` (required, string): Target format (mp4, webm, avi, mov, etc.)

**Example Request**:
```json
{
  "video_filename": "video.mp4",
  "target_format": "webm"
}
```

**Example Response**:
```json
{
  "status": "success",
  "filename": "video.webm",
  "path": "/data/video.webm"
}
```

### `cleanup_files`

Manually triggers cleanup of old files.

**Parameters**:
- `retention_days` (optional, integer): Override retention period for this cleanup (defaults to `CLEANUP_RETENTION_DAYS`)

**Example Request**:
```json
{
  "retention_days": 3
}
```

**Example Response**:
```json
{
  "status": "success",
  "files_deleted": 5,
  "retention_days": 3
}
```

## MCP Client Setup

The MCP server is accessible via HTTP transport on port 8000, allowing network-based access from any MCP client.

### HTTP Endpoint

- **Docker Network**: `http://ytdlp-mcp:8000`
- **Host Machine**: `http://localhost:8000`

### Claude Desktop

To connect Claude Desktop to this MCP server, add the following to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "ytdlp-mcp": {
      "url": "http://localhost:8000",
      "transport": "http"
    }
  }
}
```

### Other MCP Clients

The service uses standard MCP protocol over HTTP, making it compatible with any MCP client that supports HTTP transport. Configure your client to connect to:
- `http://ytdlp-mcp:8000` (from within Docker network)
- `http://localhost:8000` (from host)

## Troubleshooting

### Common Issues

#### Container won't start
- **Check Docker logs**: `docker-compose logs ytdlp-mcp`
- **Verify volume paths exist**: Ensure your configured data directory path exists
- **Check permissions**: Ensure the directory has appropriate read/write permissions
- **Verify environment variable syntax**: Check for typos in docker-compose.yaml

#### Downloads fail
- **Verify network connectivity**: Ensure the container can reach the internet
- **Check cookies file path**: If using authentication, verify the cookies file path is correct and accessible
- **Review yt-dlp errors**: Check container logs for detailed error messages
- **Test URL manually**: Verify the video URL is accessible

#### Files not accessible
- **Verify volume mount**: Ensure the volume path in docker-compose.yaml is correct
- **Check file permissions**: Files should be readable/writable
- **Verify OUTPUT_DIRECTORY**: Ensure it matches the volume mount point in docker-compose.yaml
- **Check file paths**: Use the exact filename returned by the MCP tool

#### MCP client can't connect
- **Verify port is exposed**: Check `ports: - "8000:8000"` in docker-compose.yaml
- **Test HTTP endpoint**: Try `curl http://localhost:8000` from host
- **Check firewall**: Ensure port 8000 is not blocked
- **Verify container is running**: `docker-compose ps`

### Debugging

**View container logs**:
```bash
docker-compose logs -f ytdlp-mcp
```

**Check container status**:
```bash
docker-compose ps
```

**Test HTTP endpoint**:
```bash
curl http://localhost:8000
```

**Execute commands in container**:
```bash
docker-compose exec ytdlp-mcp /bin/bash
```

**Check file permissions**:
```bash
docker-compose exec ytdlp-mcp ls -la /data
```

## Examples

### Basic Workflow

1. **Download a video**:
   ```json
   {
     "url": "https://www.youtube.com/watch?v=example"
   }
   ```

2. **Access video metadata** (included in download response):
   The download response includes a `metadata` object with thumbnail URLs, video information, and statistics.

3. **Convert to WebM format**:
   ```json
   {
     "video_filename": "downloaded_video.mp4",
     "target_format": "webm"
   }
   ```

### Using Cookies for Authentication

1. **Export cookies from browser** (using browser extension or yt-dlp)
2. **Place cookies file in accessible location** (e.g., shared volume)
3. **Download with authentication**:
   ```json
   {
     "url": "https://www.youtube.com/watch?v=age-restricted-video",
     "cookies_file": "/data/cookies.txt"
   }
   ```

### Custom Filename Formats

**Default - Video ID from URL**:
```yaml
environment:
  - VIDEO_FILENAME_FORMAT=%(id)s.%(ext)s
```
This uses the video ID extracted from the URL (e.g., `dQw4w9WgXcQ.mp4` for YouTube videos).

**Title with 100 char limit**:
```yaml
environment:
  - VIDEO_FILENAME_FORMAT=%(title).100s.%(ext)s
```

**Organize by uploader and date**:
```yaml
environment:
  - VIDEO_FILENAME_FORMAT=%(uploader)s/%(upload_date)s - %(id)s.%(ext)s
```

**Simple title-based naming**:
```yaml
environment:
  - VIDEO_FILENAME_FORMAT=%(title)s.%(ext)s
```

## Architecture

This service runs as a standalone Docker container providing MCP tools for media processing:

- **Isolation**: Video processing runs in its own container, isolated from other services
- **Persistent Storage**: Volume mount (`/data`) for file storage and access
- **Network Communication**: MCP protocol over HTTP enables LLM integration
- **Automatic Cleanup**: Background thread removes old files based on configurable retention period

### Benefits

- **Standalone**: No dependencies on other services
- **Flexibility**: Configurable via environment variables
- **Integration**: Direct LLM access via MCP protocol
- **Maintainability**: Simple, focused service for media processing operations

## License

[Add your license information here]

