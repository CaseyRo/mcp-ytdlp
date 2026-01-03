# Media Processing Sidecar Service

A FastMCP-based microservice for downloading videos, converting formats, extracting screenshots, and managing media files. Designed to work alongside n8n workflows as a sidecar container.

## Overview

This service provides MCP (Model Context Protocol) tools for media processing operations:
- **Video Download**: Download videos from URLs using yt-dlp with optional authentication
- **Video Conversion**: Convert videos between formats using FFmpeg
- **Screenshot Extraction**: Extract frames from videos at specific timestamps
- **File Cleanup**: Automatic and manual cleanup of old files

The service runs as a Docker container alongside n8n, sharing a volume for file exchange while keeping video processing isolated from workflow orchestration.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Existing n8n setup (optional, but designed to work alongside n8n)
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
     - /mnt/data/AI/n8n:/data  # Update to match your n8n volume
   ```

3. **Configure environment variables** (see Configuration section below)

4. **Start the service**:
   ```bash
   docker-compose up -d
   ```

5. **Verify the service is running**:
   ```bash
   docker-compose logs media-sidecar
   ```

### Basic Usage

The MCP server is accessible via HTTP on port 8000. Connect your MCP client to:
- `http://media-sidecar:8000` (from within Docker network)
- `http://localhost:8000` (from host machine)

## Configuration

### Environment Variables

All configuration is done via environment variables in `docker-compose.yaml`:

#### `OUTPUT_DIRECTORY`
- **Default**: `/data`
- **Description**: Directory where all downloaded videos, converted videos, and screenshots are saved
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

#### `SCREENSHOT_FILENAME_FORMAT`
- **Default**: `{video_filename}_{timestamp}.jpg`
- **Description**: Filename format for screenshot files
- **Format Variables**: `%(video_filename)s`, `%(timestamp)s`, or `{video_filename}`, `{timestamp}`
- **Example**:
  ```yaml
  environment:
    - SCREENSHOT_FILENAME_FORMAT=screenshot_%(video_filename)s_%(timestamp)s.jpg
  ```

### Docker Compose Configuration

Example `docker-compose.yaml` configuration:

```yaml
services:
  media-sidecar:
    build: .
    container_name: n8n-media-sidecar
    restart: unless-stopped
    volumes:
      - /mnt/data/AI/n8n:/data
    environment:
      - OUTPUT_DIRECTORY=/data
      - CLEANUP_RETENTION_DAYS=7
      - VIDEO_FILENAME_FORMAT=%(title)s.%(ext)s
      - SCREENSHOT_FILENAME_FORMAT=%(video_filename)s_%(timestamp)s.jpg
    ports:
      - "8000:8000"
    networks:
      - n8n-network
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
  "path": "/data/video.mp4"
}
```

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

### `extract_screenshot`

Extracts a single frame from a video at a specified timestamp.

**Parameters**:
- `video_filename` (required, string): Name of the video file
- `timestamp` (required, string): Timestamp in HH:MM:SS format (e.g., "00:01:30")

**Example Request**:
```json
{
  "video_filename": "video.mp4",
  "timestamp": "00:01:30"
}
```

**Example Response**:
```json
{
  "status": "success",
  "screenshot_filename": "video_00130.jpg",
  "path": "/data/video_00130.jpg"
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

- **Docker Network**: `http://media-sidecar:8000`
- **Host Machine**: `http://localhost:8000`

### Claude Desktop

To connect Claude Desktop to this MCP server, add the following to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "media-sidecar": {
      "url": "http://localhost:8000",
      "transport": "http"
    }
  }
}
```

### Other MCP Clients

The service uses standard MCP protocol over HTTP, making it compatible with any MCP client that supports HTTP transport. Configure your client to connect to:
- `http://media-sidecar:8000` (from within Docker network)
- `http://localhost:8000` (from host)

## Troubleshooting

### Common Issues

#### Container won't start
- **Check Docker logs**: `docker-compose logs media-sidecar`
- **Verify volume paths exist**: Ensure `/mnt/data/AI/n8n` (or your configured path) exists
- **Check permissions**: Ensure the directory has appropriate read/write permissions
- **Verify environment variable syntax**: Check for typos in docker-compose.yaml

#### Downloads fail
- **Verify network connectivity**: Ensure the container can reach the internet
- **Check cookies file path**: If using authentication, verify the cookies file path is correct and accessible
- **Review yt-dlp errors**: Check container logs for detailed error messages
- **Test URL manually**: Verify the video URL is accessible

#### Files not accessible in n8n
- **Verify shared volume**: Ensure both containers mount the same volume path
- **Check file permissions**: Files should be readable by n8n user
- **Verify OUTPUT_DIRECTORY**: Ensure it matches the n8n volume mount point
- **Check file paths**: Use the exact filename returned by the MCP tool

#### MCP client can't connect
- **Verify port is exposed**: Check `ports: - "8000:8000"` in docker-compose.yaml
- **Test HTTP endpoint**: Try `curl http://localhost:8000` from host
- **Check firewall**: Ensure port 8000 is not blocked
- **Verify container is running**: `docker-compose ps`

### Debugging

**View container logs**:
```bash
docker-compose logs -f media-sidecar
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
docker-compose exec media-sidecar /bin/bash
```

**Check file permissions**:
```bash
docker-compose exec media-sidecar ls -la /data
```

## Examples

### Basic Workflow

1. **Download a video**:
   ```json
   {
     "url": "https://www.youtube.com/watch?v=example"
   }
   ```

2. **Extract a screenshot at 1 minute**:
   ```json
   {
     "video_filename": "downloaded_video.mp4",
     "timestamp": "00:01:00"
   }
   ```

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

**Screenshot with video metadata**:
```yaml
environment:
  - SCREENSHOT_FILENAME_FORMAT=%(video_filename)s_frame_%(timestamp)s.jpg
```

## Architecture

This service follows the **sidecar pattern**, running as a separate container alongside n8n:

- **Isolation**: Video processing runs in a separate container, preventing CPU-intensive operations from impacting n8n workflows
- **Shared Storage**: Both containers share a volume (`/data`) for file exchange
- **Network Communication**: MCP protocol over HTTP enables LLM integration
- **Automatic Cleanup**: Background thread removes old files based on configurable retention period

### Benefits

- **Stability**: Video processing won't crash n8n workflows
- **Maintainability**: Update n8n and media tools independently
- **Flexibility**: Configurable via environment variables
- **Integration**: Direct LLM access via MCP protocol

## License

[Add your license information here]

