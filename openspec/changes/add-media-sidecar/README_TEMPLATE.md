# Media Processing Sidecar Service

[This is a template for the README.md that will be created during implementation]

## Overview

Brief description of what this service does and why it exists.

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Existing n8n setup (optional, but designed to work alongside n8n)

### Installation

1. Clone or copy the service files to your project directory
2. Update `docker-compose.yaml` with your volume paths
3. Configure environment variables (see Configuration section)
4. Start the service: `docker-compose up -d`

### Basic Usage

Example of connecting an MCP client and using a tool.

## Configuration

### Environment Variables

#### `OUTPUT_DIRECTORY`
- **Default**: `/data`
- **Description**: Directory where all downloaded videos, converted videos, and screenshots are saved
- **Example**: `OUTPUT_DIRECTORY=/mnt/storage/videos`

#### `CLEANUP_RETENTION_DAYS`
- **Default**: `7`
- **Description**: Number of days to retain files before automatic cleanup removes them
- **Example**: `CLEANUP_RETENTION_DAYS=14`

#### `VIDEO_FILENAME_FORMAT`
- **Default**: Auto-generated unique filename
- **Description**: Filename format for downloaded videos using yt-dlp formatting syntax
- **Format Variables**: `%(title)s`, `%(id)s`, `%(ext)s`, `%(uploader)s`, etc.
- **Example**: `VIDEO_FILENAME_FORMAT=%(title)s - %(uploader)s.%(ext)s`

#### `SCREENSHOT_FILENAME_FORMAT`
- **Default**: `{video_filename}_{timestamp}.jpg`
- **Description**: Filename format for screenshot files
- **Format Variables**: `%(video_filename)s`, `%(timestamp)s`
- **Example**: `SCREENSHOT_FILENAME_FORMAT=screenshot_%(video_filename)s_%(timestamp)s.jpg`

### Docker Compose Configuration

Example docker-compose.yaml configuration with all options.

## MCP Tools Reference

### `download_video`
Downloads a video from a URL using yt-dlp.

**Parameters**:
- `url` (required): Video URL to download
- `cookies_file` (optional): Path to cookies file for authentication

**Example**:
```json
{
  "url": "https://www.youtube.com/watch?v=example",
  "cookies_file": "/path/to/cookies.txt"
}
```

**Response**:
```json
{
  "status": "success",
  "filename": "video.mp4",
  "path": "/data/video.mp4"
}
```

### `convert_video`
Converts a video file to a different format.

**Parameters**:
- `video_filename` (required): Name of the video file to convert
- `target_format` (required): Target format (mp4, webm, avi, mov, etc.)

**Example**:
```json
{
  "video_filename": "video.mp4",
  "target_format": "webm"
}
```

### `extract_screenshot`
Extracts a single frame from a video at a specified timestamp.

**Parameters**:
- `video_filename` (required): Name of the video file
- `timestamp` (required): Timestamp in HH:MM:SS format

**Example**:
```json
{
  "video_filename": "video.mp4",
  "timestamp": "00:01:30"
}
```

### `cleanup_files`
Manually triggers cleanup of old files.

**Parameters**:
- `retention_days` (optional): Override retention period for this cleanup (defaults to `CLEANUP_RETENTION_DAYS`)

**Example**:
```json
{
  "retention_days": 3
}
```

## MCP Client Setup

The MCP server is accessible via HTTP transport on port 8000, allowing network-based access from any MCP client.

### HTTP Endpoint

The MCP server is available at: `http://media-sidecar:8000` (from within Docker network) or `http://localhost:8000` (from host)

### Claude Desktop

Configuration example for Claude Desktop MCP settings using HTTP transport.

### Other MCP Clients

Generic instructions for connecting any MCP client via HTTP transport. The service uses standard MCP protocol over HTTP, making it compatible with any MCP client that supports HTTP transport.

## Troubleshooting

### Common Issues

#### Container won't start
- Check Docker logs: `docker-compose logs media-sidecar`
- Verify volume paths exist and have correct permissions
- Check environment variable syntax

#### Downloads fail
- Verify network connectivity
- Check if cookies file path is correct (if using authentication)
- Review yt-dlp error messages in logs

#### Files not accessible in n8n
- Verify shared volume is mounted correctly
- Check file permissions
- Ensure OUTPUT_DIRECTORY matches n8n volume mount

### Debugging

How to view logs, check service status, etc.

## Examples

### Basic Workflow
Example of downloading a video and extracting a screenshot.

### Using Cookies for Authentication
Example of downloading age-restricted content.

### Custom Filename Formats
Examples of different filename format configurations.

## Architecture

Brief overview of the sidecar pattern and how it integrates with n8n.

