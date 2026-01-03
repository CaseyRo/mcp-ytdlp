#!/usr/bin/env python3
"""
Media Processing Sidecar Service
FastMCP server for video download, conversion, screenshot extraction, and cleanup
"""

import os
import subprocess
import uuid
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any, Dict

from fastmcp import FastMCP

# Configuration from environment variables
OUTPUT_DIR = os.getenv("OUTPUT_DIRECTORY", "/data")
CLEANUP_RETENTION_DAYS = int(os.getenv("CLEANUP_RETENTION_DAYS", "7"))
VIDEO_FILENAME_FORMAT = os.getenv("VIDEO_FILENAME_FORMAT")
SCREENSHOT_FILENAME_FORMAT = os.getenv("SCREENSHOT_FILENAME_FORMAT", "{video_filename}_{timestamp}.jpg")

# Ensure output directory exists
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Initialize FastMCP server
mcp = FastMCP("Media Processing Sidecar")

# Progress tracking storage (in-memory, keyed by task ID)
progress_store = {}


def format_filename(template: str, **kwargs) -> str:
    """Format filename using template with provided variables."""
    try:
        return template.format(**kwargs)
    except KeyError:
        # Fallback to simple replacement
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
            result = result.replace(f"%({key})s", str(value))
        return result


def get_video_filename(url: str, ext: str = "mp4") -> str:
    """Generate video filename based on format or default."""
    if VIDEO_FILENAME_FORMAT:
        # yt-dlp will handle formatting via --output template
        # We'll use the format directly in the output template
        return VIDEO_FILENAME_FORMAT
    else:
        # Default: unique filename
        file_id = str(uuid.uuid4())
        return f"{file_id}.%(ext)s"


def cleanup_old_files(retention_days: Optional[int] = None):
    """Clean up files older than retention period."""
    if retention_days is None:
        retention_days = CLEANUP_RETENTION_DAYS

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0

    output_path = Path(OUTPUT_DIR)
    if not output_path.exists():
        return deleted_count

    # Video file extensions
    video_extensions = {'.mp4', '.webm', '.avi', '.mov', '.mkv', '.flv', '.m4v'}

    for file_path in output_path.iterdir():
        if file_path.is_file():
            # Check if it's a video file
            if file_path.suffix.lower() in video_extensions:
                # Check file creation time
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_ctime)
                    if file_time < cutoff_date:
                        file_path.unlink()
                        deleted_count += 1
                except (OSError, ValueError):
                    # Skip files we can't process
                    continue

    return deleted_count


def run_cleanup_periodically():
    """Background thread to run cleanup periodically."""
    while True:
        time.sleep(3600)  # Run every hour
        try:
            cleanup_old_files()
        except Exception as e:
            print(f"Error in periodic cleanup: {e}")


# Start background cleanup thread
cleanup_thread = threading.Thread(target=run_cleanup_periodically, daemon=True)
cleanup_thread.start()


@mcp.tool()
def download_video(
    url: str = None,
    cookies_file: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
    recipe: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    webhookUrl: Optional[str] = None,
    executionMode: Optional[str] = None,
    ts_baseurl: Optional[str] = None,
    toolCallId: Optional[str] = None
) -> dict:
    """
    Download a video from a URL using yt-dlp.

    Args:
        url: Video URL to download (can be in body.recipe.url if nested)
        cookies_file: Optional path to cookies file for authentication
        body: Optional body dict containing nested parameters
        **kwargs: Additional parameters (ignored, for MCP client compatibility)

    Returns:
        Dictionary with status, filename, and path
    """
    try:
        # Extract URL from various possible locations (MCP client may nest it)
        if not url:
            if body and isinstance(body, dict):
                if 'recipe' in body and isinstance(body['recipe'], dict):
                    url = body['recipe'].get('url')
                elif 'url' in body:
                    url = body.get('url')
            if not url and 'url' in kwargs:
                url = kwargs.get('url')

        if not url:
            return {
                "status": "error",
                "error": "URL is required. Provide 'url' parameter or 'body.recipe.url'"
            }

        # Extract cookies_file from various possible locations
        if not cookies_file or cookies_file == "[null]":
            if body and isinstance(body, dict):
                if 'recipe' in body and isinstance(body['recipe'], dict):
                    cookies_file = body['recipe'].get('cookies_file')
                elif 'cookies_file' in body:
                    cookies_file = body.get('cookies_file')
            if (not cookies_file or cookies_file == "[null]") and 'cookies_file' in kwargs:
                cookies_file = kwargs.get('cookies_file')

        # Clean up cookies_file value
        if cookies_file == "[null]" or cookies_file == "null":
            cookies_file = None

        # Build output template
        if VIDEO_FILENAME_FORMAT:
            # Use custom format from environment variable
            output_template = f"{OUTPUT_DIR}/{VIDEO_FILENAME_FORMAT}"
        else:
            # Default: use video ID (last part of URL) as filename
            output_template = f"{OUTPUT_DIR}/%(id)s.%(ext)s"

        # Build yt-dlp command
        # Use simpler format: best[ext=mp4] for direct MP4 download
        command = [
            "yt-dlp",
            "--format", "best[ext=mp4]",
            "--output", output_template,
            "--no-playlist",
        ]

        # Add cookies file if provided
        if cookies_file and cookies_file != "[null]":
            command.extend(["--cookies", cookies_file])

        command.append(url)

        # Run yt-dlp
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )

        # Find the downloaded file by looking for recently created files
        # Since we use yt-dlp format, we need to find the file by checking modification time
        output_path = Path(OUTPUT_DIR)
        if not output_path.exists():
            raise Exception(f"Output directory does not exist: {OUTPUT_DIR}")

        # Get the most recently created/modified file (should be the one we just downloaded)
        files = list(output_path.iterdir())
        if not files:
            raise Exception("No files found in output directory after download")

        # Sort by modification time, most recent first
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        most_recent = files[0]

        # Verify it's a video file
        video_extensions = {'.mp4', '.webm', '.avi', '.mov', '.mkv', '.flv', '.m4v'}
        if most_recent.suffix.lower() not in video_extensions:
            raise Exception(f"Downloaded file is not a video: {most_recent.name}")

        return {
            "status": "success",
            "filename": most_recent.name,
            "path": str(most_recent)
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": f"Download failed: {e.stderr or str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
def convert_video(
    video_filename: str,
    target_format: str,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    webhookUrl: Optional[str] = None,
    executionMode: Optional[str] = None,
    ts_baseurl: Optional[str] = None,
    toolCallId: Optional[str] = None
) -> dict:
    """
    Convert a video file to a different format using FFmpeg.

    Args:
        video_filename: Name of the video file to convert
        target_format: Target format (mp4, webm, avi, mov, etc.)
        headers, params, query, body, webhookUrl, executionMode, ts_baseurl, toolCallId:
            Additional parameters (ignored, for MCP client compatibility)

    Returns:
        Dictionary with status, output filename, and path
    """
    try:

        input_path = Path(OUTPUT_DIR) / video_filename
        if not input_path.exists():
            return {
                "status": "error",
                "error": f"Video file not found: {video_filename}"
            }

        # Generate output filename
        output_filename = f"{input_path.stem}.{target_format}"
        output_path = Path(OUTPUT_DIR) / output_filename

        # FFmpeg conversion command
        command = [
            "ffmpeg",
            "-i", str(input_path),
            "-c:v", "libx264",  # Video codec
            "-c:a", "aac",  # Audio codec
            "-y",  # Overwrite output file
            str(output_path)
        ]

        # Run FFmpeg
        subprocess.run(command, check=True, capture_output=True)

        return {
            "status": "success",
            "filename": output_filename,
            "path": str(output_path)
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": f"Conversion failed: {e.stderr.decode() if e.stderr else str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
def extract_screenshot(
    video_filename: str,
    timestamp: str,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    webhookUrl: Optional[str] = None,
    executionMode: Optional[str] = None,
    ts_baseurl: Optional[str] = None,
    toolCallId: Optional[str] = None
) -> dict:
    """
    Extract a single frame from a video at a specified timestamp.

    Args:
        video_filename: Name of the video file
        timestamp: Timestamp in HH:MM:SS format
        headers, params, query, body, webhookUrl, executionMode, ts_baseurl, toolCallId:
            Additional parameters (ignored, for MCP client compatibility)

    Returns:
        Dictionary with status, screenshot filename, and path
    """
    try:

        input_path = Path(OUTPUT_DIR) / video_filename
        if not input_path.exists():
            return {
                "status": "error",
                "error": f"Video file not found: {video_filename}"
            }

        # Format screenshot filename
        timestamp_clean = timestamp.replace(":", "")
        if SCREENSHOT_FILENAME_FORMAT:
            screenshot_filename = format_filename(
                SCREENSHOT_FILENAME_FORMAT,
                video_filename=video_filename,
                timestamp=timestamp_clean
            )
        else:
            screenshot_filename = f"{input_path.stem}_{timestamp_clean}.jpg"

        output_path = Path(OUTPUT_DIR) / screenshot_filename

        # FFmpeg command to extract frame
        command = [
            "ffmpeg",
            "-ss", timestamp,
            "-i", str(input_path),
            "-frames:v", "1",
            "-q:v", "2",  # High quality JPEG
            "-y",  # Overwrite
            str(output_path)
        ]

        # Run FFmpeg
        subprocess.run(command, check=True, capture_output=True)

        return {
            "status": "success",
            "screenshot_filename": screenshot_filename,
            "path": str(output_path)
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": f"Screenshot extraction failed: {e.stderr.decode() if e.stderr else str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
def cleanup_files(
    retention_days: Optional[int] = None,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    webhookUrl: Optional[str] = None,
    executionMode: Optional[str] = None,
    ts_baseurl: Optional[str] = None,
    toolCallId: Optional[str] = None
) -> dict:
    """
    Manually trigger cleanup of old files.

    Args:
        retention_days: Optional retention period in days (overrides CLEANUP_RETENTION_DAYS)
        headers, params, query, body, webhookUrl, executionMode, ts_baseurl, toolCallId:
            Additional parameters (ignored, for MCP client compatibility)

    Returns:
        Dictionary with status and number of files deleted
    """
    try:
        deleted_count = cleanup_old_files(retention_days)
        return {
            "status": "success",
            "files_deleted": deleted_count,
            "retention_days": retention_days or CLEANUP_RETENTION_DAYS
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


if __name__ == "__main__":
    # Run FastMCP server with HTTP transport
    # FastMCP can be run directly with uvicorn
    import uvicorn

    # FastMCP exposes an ASGI app via the mcp object
    # We'll use uvicorn to serve it over HTTP
    try:
        # Try FastMCP's built-in run method if available
        mcp.run(host="0.0.0.0", port=8000, transport="http")
    except (AttributeError, TypeError):
        # Fallback: use uvicorn directly with the MCP app
        # FastMCP should expose an ASGI application
        app = mcp.create_app() if hasattr(mcp, 'create_app') else mcp
        uvicorn.run(app, host="0.0.0.0", port=8000)

