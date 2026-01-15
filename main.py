#!/usr/bin/env python3
"""
Media Processing Sidecar Service
FastMCP server for video download, conversion, and cleanup
"""

import os
import subprocess
import uuid
import threading
import time
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Tuple

from fastmcp import FastMCP

# Configuration from environment variables
OUTPUT_DIR = os.getenv("OUTPUT_DIRECTORY", "/data")
CLEANUP_RETENTION_DAYS = int(os.getenv("CLEANUP_RETENTION_DAYS", "7"))
VIDEO_FILENAME_FORMAT = os.getenv("VIDEO_FILENAME_FORMAT")

# Ensure output directory exists
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Initialize FastMCP server
mcp = FastMCP("Media Processing Sidecar")

# Progress tracking storage (in-memory, keyed by task ID)
progress_store = {}

# Cache for yt-dlp version info (check once per hour)
_version_cache = {"version": None, "latest_version": None, "update_available": None, "last_check": None}


def get_ytdlp_version() -> str:
    """Get the installed yt-dlp version."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def get_latest_ytdlp_version() -> Optional[str]:
    """Get the latest available yt-dlp version from PyPI."""
    try:
        import urllib.request
        import urllib.error
        
        # Query PyPI JSON API
        url = "https://pypi.org/pypi/yt-dlp/json"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except Exception as e:
        print(f"Warning: Failed to check latest yt-dlp version: {e}")
        return None


def compare_versions(current: str, latest: Optional[str]) -> bool:
    """Compare version strings to determine if update is available."""
    if not latest or current == "unknown":
        return False
    
    try:
        # yt-dlp uses date-based versioning (e.g., "2025.12.08")
        # Split by '.' and compare as integers
        current_parts = [int(x) for x in re.findall(r'\d+', current.split('.')[0])]
        latest_parts = [int(x) for x in re.findall(r'\d+', latest.split('.')[0])]
        
        # Compare year, month, day
        for i in range(min(len(current_parts), len(latest_parts))):
            if latest_parts[i] > current_parts[i]:
                return True
            elif latest_parts[i] < current_parts[i]:
                return False
        
        # If same date, compare remaining parts (like dev versions)
        if len(latest_parts) > len(current_parts):
            return True
        
        # Check if latest has additional version components (e.g., .dev0)
        if latest != current:
            # Simple string comparison for dev/pre-release versions
            return latest > current
        
        return False
    except (ValueError, AttributeError):
        # Fallback: simple string comparison
        return latest > current if latest and current else False


def get_ytdlp_version_info(force_check: bool = False) -> Dict[str, Any]:
    """Get yt-dlp version information, with caching."""
    global _version_cache
    
    # Check cache (valid for 1 hour)
    now = time.time()
    if not force_check and _version_cache["last_check"]:
        cache_age = now - _version_cache["last_check"]
        if cache_age < 3600:  # 1 hour
            return {
                "yt_dlp_version": _version_cache["version"],
                "latest_available_version": _version_cache["latest_version"],
                "update_available": _version_cache["update_available"]
            }
    
    # Get current version
    current_version = get_ytdlp_version()
    
    # Get latest version
    latest_version = get_latest_ytdlp_version()
    
    # Check if update is available
    update_available = compare_versions(current_version, latest_version)
    
    # Update cache
    _version_cache = {
        "version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "last_check": now
    }
    
    return {
        "yt_dlp_version": current_version,
        "latest_available_version": latest_version,
        "update_available": update_available
    }


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
    output_directory: Optional[str] = None,
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
        output_directory: Optional output directory path. If not provided, uses OUTPUT_DIRECTORY environment variable or default /data
        body: Optional body dict containing nested parameters
        headers, params, query, recipe, webhookUrl, executionMode, ts_baseurl, toolCallId:
            Additional parameters (ignored, for MCP client compatibility)

    Returns:
        Dictionary with status, filename, path, and metadata (if available)
    """
    try:
        # Extract URL from various possible locations (MCP client may nest it)
        if not url:
            if body and isinstance(body, dict):
                if 'recipe' in body and isinstance(body['recipe'], dict):
                    url = body['recipe'].get('url')
                elif 'url' in body:
                    url = body.get('url')

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

        # Clean up cookies_file value
        if cookies_file == "[null]" or cookies_file == "null":
            cookies_file = None

        # Determine output directory (parameter takes precedence over env var)
        output_dir = output_directory if output_directory else OUTPUT_DIR
        output_dir_path = Path(output_dir)

        # Ensure output directory exists
        output_dir_path.mkdir(parents=True, exist_ok=True)

        # First, extract metadata using yt-dlp --dump-json --skip-download
        metadata = None
        metadata_command = [
            "yt-dlp",
            "--dump-json",
            "--skip-download",
            "--no-playlist",
        ]

        # Add cookies file if provided
        if cookies_file and cookies_file != "[null]":
            metadata_command.extend(["--cookies", cookies_file])

        metadata_command.append(url)

        try:
            # Extract metadata
            metadata_result = subprocess.run(
                metadata_command,
                capture_output=True,
                text=True,
                check=True
            )
            # Parse JSON metadata
            metadata = json.loads(metadata_result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            # If metadata extraction fails, continue with download but log warning
            print(f"Warning: Failed to extract metadata: {e}")

        # Build output template
        if VIDEO_FILENAME_FORMAT:
            # Use custom format from environment variable
            output_template = f"{output_dir}/{VIDEO_FILENAME_FORMAT}"
        else:
            # Default: use video ID (last part of URL) as filename
            output_template = f"{output_dir}/%(id)s.%(ext)s"

        # Build yt-dlp command for download
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

        # Run yt-dlp to download
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )

        # Find the downloaded file by looking for recently created files
        # Since we use yt-dlp format, we need to find the file by checking modification time
        output_path = output_dir_path
        if not output_path.exists():
            raise Exception(f"Output directory does not exist: {output_dir}")

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

        # Prepare response with metadata
        response = {
            "status": "success",
            "filename": most_recent.name,
            "path": str(most_recent)
        }

        # Get yt-dlp version information
        version_info = get_ytdlp_version_info()
        
        # Include metadata if available
        if metadata:
            # Extract relevant metadata fields
            response["metadata"] = {
                "id": metadata.get("id"),
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "duration": metadata.get("duration"),
                "thumbnail": metadata.get("thumbnail"),
                "thumbnails": metadata.get("thumbnails", []),
                "uploader": metadata.get("uploader"),
                "uploader_id": metadata.get("uploader_id"),
                "channel": metadata.get("channel"),
                "channel_id": metadata.get("channel_id"),
                "upload_date": metadata.get("upload_date"),
                "view_count": metadata.get("view_count"),
                "like_count": metadata.get("like_count"),
                "webpage_url": metadata.get("webpage_url"),
            }
        
        # Always include version information in response
        response["yt_dlp"] = version_info

        return response

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
