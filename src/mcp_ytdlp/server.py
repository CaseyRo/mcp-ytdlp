#!/usr/bin/env python3
"""
Media Processing Sidecar Service
FastMCP server for video download, conversion, and cleanup
"""

import hmac
import os
import subprocess
import uuid
import threading
import time
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Annotated, Literal, Optional, Any, Dict, Tuple

from fastmcp import FastMCP

# Configuration from environment variables
OUTPUT_DIR = os.getenv("OUTPUT_DIRECTORY", "/data")
CLEANUP_RETENTION_DAYS = int(os.getenv("CLEANUP_RETENTION_DAYS", "7"))
VIDEO_FILENAME_FORMAT = os.getenv("VIDEO_FILENAME_FORMAT")

# Ensure output directory exists
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

from .auth import BearerTokenVerifier


def _validate_url(url: str) -> None:
    """Reject non-http(s) URLs and loopback/link-local hosts before handing to yt-dlp.

    yt-dlp supports file://, data:, and other protocol handlers that would let
    a caller read arbitrary files or reach internal network resources.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme!r}")
    hostname = (parsed.hostname or "").lower()
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.startswith(
        "169.254."
    ):
        raise ValueError("Disallowed URL host")


def _validate_cookies_path(cookies_file: str) -> Path:
    """Confine cookies_file to OUTPUT_DIR and reject path traversal.

    Without this, --cookies would accept arbitrary paths like /etc/passwd.
    """
    safe_name = Path(cookies_file).name
    if safe_name != cookies_file or ".." in cookies_file:
        raise ValueError("cookies_file must be a plain filename without path separators")
    resolved = (Path(OUTPUT_DIR) / safe_name).resolve()
    if not str(resolved).startswith(str(Path(OUTPUT_DIR).resolve())):
        raise ValueError("cookies_file path escapes output directory")
    if not resolved.exists():
        raise ValueError(f"cookies_file not found: {safe_name}")
    return resolved


_api_key = os.getenv("MCP_API_KEY", "")
_transport = os.getenv("MCP_TRANSPORT", "streamable-http")
if _transport in ("http", "streamable-http") and not _api_key:
    raise SystemExit(
        "MCP_API_KEY is required in HTTP mode. Refusing to start "
        "an unauthenticated server."
    )
_auth = BearerTokenVerifier(api_key=_api_key) if _api_key else None

# Initialize FastMCP server
mcp = FastMCP("Media Processing Sidecar", auth=_auth)

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


def parse_ytdlp_error(stderr: str, url: str) -> str:
    """
    Parse yt-dlp stderr output to extract user-friendly error messages.
    
    Args:
        stderr: The stderr output from yt-dlp
        url: The URL that was being processed
        
    Returns:
        A user-friendly error message
    """
    if not stderr:
        return f"Failed to process video from URL: {url}"
    
    stderr_lower = stderr.lower()
    
    # Check for common error patterns
    if "404" in stderr or "not found" in stderr_lower or "does not exist" in stderr_lower:
        return f"Video not found (404): The video at {url} does not exist or has been removed."
    
    if "unavailable" in stderr_lower or "unavailable" in stderr:
        return f"Video unavailable: The video at {url} is unavailable. It may be private, deleted, or restricted."
    
    if "private" in stderr_lower:
        return f"Video is private: The video at {url} is private and cannot be accessed."
    
    if "age-restricted" in stderr_lower or "age restricted" in stderr_lower:
        return f"Age-restricted video: The video at {url} is age-restricted and may require authentication."
    
    if "geoblocked" in stderr_lower or "geoblock" in stderr_lower:
        return f"Geoblocked video: The video at {url} is not available in your region."
    
    if "copyright" in stderr_lower or "copyright" in stderr:
        return f"Copyright restriction: The video at {url} cannot be accessed due to copyright restrictions."
    
    if "sign in" in stderr_lower or "login" in stderr_lower:
        return f"Authentication required: The video at {url} requires sign-in. Consider using a cookies file."
    
    # Extract the first meaningful error line (usually contains the actual error message)
    lines = stderr.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line and not line.startswith('[') and 'error' in line.lower():
            # Return the first error line that seems meaningful
            if len(line) > 20:  # Skip very short lines
                return f"Error processing {url}: {line}"
    
    # Fallback: return the last non-empty line or the whole stderr
    error_lines = [line.strip() for line in lines if line.strip()]
    if error_lines:
        last_line = error_lines[-1]
        # Don't include the full stderr if it's too verbose
        if len(last_line) < 500:
            return f"Error processing {url}: {last_line}"
    
    return f"Failed to process video from {url}. yt-dlp error: {stderr[:200]}..."


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
    url: Annotated[str, "Video URL to download (YouTube, Vimeo, etc.)"],
    cookies_file: Optional[str] = None,
    output_directory: Optional[str] = None,
) -> dict:
    """[media] Download a video from a URL using yt-dlp.

    Args:
        url: Video URL to download
        cookies_file: Optional path to cookies file for authentication
        output_directory: Optional output directory path. Defaults to OUTPUT_DIRECTORY env var or /data.

    Returns:
        Dictionary with status, filename, path, and metadata (if available)
    """
    try:
        print(f"[download_video] Request received")
        print(f"[download_video] URL: {url}")

        try:
            _validate_url(url)
        except ValueError as e:
            return {"status": "error", "error": str(e), "url": url}

        # Clean up cookies_file value
        if cookies_file in ("[null]", "null", ""):
            cookies_file = None

        if cookies_file:
            print("[download_video] cookies_file provided")
            try:
                cookies_file = str(_validate_cookies_path(cookies_file))
            except ValueError as e:
                return {"status": "error", "error": str(e), "url": url}

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
        except subprocess.CalledProcessError as e:
            # If metadata extraction fails, it likely means the video is unavailable
            # Return a clear error message instead of continuing
            error_msg = parse_ytdlp_error(e.stderr, url)
            print(f"[download_video] metadata extraction failed: {error_msg}")
            return {
                "status": "error",
                "error": error_msg,
                "url": url
            }
        except json.JSONDecodeError as e:
            # If we can't parse metadata JSON, log warning but continue with download
            print(f"Warning: Failed to parse metadata JSON: {e}")

        # Build output template
        if VIDEO_FILENAME_FORMAT:
            # Use custom format from environment variable
            output_template = f"{output_dir}/{VIDEO_FILENAME_FORMAT}"
        else:
            # Default: extractor prefix + id (capped to 60 chars) + ext.
            # The id cap matters for the generic extractor, which sets
            # id to the entire source URL — signed CDN URLs can run to
            # 300+ chars and trip the filesystem's filename limit
            # (Errno 36: File name too long) on ext4 / APFS.
            output_template = f"{output_dir}/%(extractor_key)s-%(id).60s.%(ext)s"

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

        print(f"[download_video] Starting download")
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
        
        print(f"[download_video] Download complete: {most_recent.name}")

        # Prepare response with metadata
        response = {
            "status": "success",
            "filename": most_recent.name,
            "path": str(most_recent)
        }

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
        
        return response

    except subprocess.CalledProcessError as e:
        error_msg = parse_ytdlp_error(e.stderr, url if 'url' in locals() else "unknown URL")
        print(f"[download_video] Download failed: {error_msg}")
        return {
            "status": "error",
            "error": error_msg,
            "url": url if 'url' in locals() else None
        }
    except Exception as e:
        print(f"[download_video] Unexpected error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


ALLOWED_FORMATS = ("mp4", "webm", "avi", "mov", "mkv")
CODEC_MAP = {
    "mp4": ("-c:v", "libx264", "-c:a", "aac"),
    "webm": ("-c:v", "libvpx-vp9", "-c:a", "libopus"),
    "avi": ("-c:v", "libx264", "-c:a", "aac"),
    "mov": ("-c:v", "libx264", "-c:a", "aac"),
    "mkv": ("-c:v", "libx264", "-c:a", "aac"),
}


@mcp.tool()
def convert_video(
    video_filename: Annotated[str, "Name of the video file in the output directory (filename only, no path)"],
    target_format: Literal["mp4", "webm", "avi", "mov", "mkv"],
) -> dict:
    """[media] Convert a video file to a different format using FFmpeg.

    Args:
        video_filename: Name of the video file to convert (must be in the output directory)
        target_format: Target format — mp4, webm, avi, mov, or mkv

    Returns:
        Dictionary with status, output filename, and path
    """
    try:
        # Path traversal protection: strip any directory components
        safe_filename = Path(video_filename).name
        if safe_filename != video_filename or ".." in video_filename:
            return {
                "status": "error",
                "error": "Invalid filename: must be a plain filename without path separators"
            }

        input_path = (Path(OUTPUT_DIR) / safe_filename).resolve()
        # Verify resolved path is still inside OUTPUT_DIR
        if not str(input_path).startswith(str(Path(OUTPUT_DIR).resolve())):
            return {
                "status": "error",
                "error": "Invalid filename: path escapes output directory"
            }

        if not input_path.exists():
            return {
                "status": "error",
                "error": f"Video file not found: {safe_filename}"
            }

        # Generate output filename with format-appropriate codecs
        output_filename = f"{input_path.stem}.{target_format}"
        output_path = Path(OUTPUT_DIR) / output_filename
        codecs = CODEC_MAP.get(target_format, ("-c:v", "libx264", "-c:a", "aac"))

        # FFmpeg conversion command
        command = [
            "ffmpeg",
            "-i", str(input_path),
            *codecs,
            "-y",  # Overwrite output file
            str(output_path)
        ]

        # Run FFmpeg with timeout to prevent indefinite blocking
        subprocess.run(command, check=True, capture_output=True, timeout=600)

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
def extract_frame(
    video_filename: Annotated[str, "Name of the video file in the output directory (filename only, no path)"],
    at_seconds: Annotated[float, "Timestamp (in seconds) to sample. Default 1.0 — the first second tends to avoid fade-in blacks while staying before titles/transitions."] = 1.0,
) -> dict:
    """[media] Extract a single still frame from a previously-downloaded video.

    Uses ffmpeg with `-ss` seek + `-frames:v 1` to pull one JPEG. The output
    is written next to the source video with the same stem + `.jpg`. Callers
    retrieve the bytes via the `GET /files/{name}` side channel.

    Args:
        video_filename: Name of the video file (must be in OUTPUT_DIRECTORY)
        at_seconds: Timestamp to sample, in seconds (must be >= 0)

    Returns:
        Dictionary with status, output filename, and path
    """
    try:
        if at_seconds < 0:
            return {"status": "error", "error": "at_seconds must be >= 0"}

        safe_filename = Path(video_filename).name
        if safe_filename != video_filename or ".." in video_filename:
            return {
                "status": "error",
                "error": "Invalid filename: must be a plain filename without path separators",
            }

        input_path = (Path(OUTPUT_DIR) / safe_filename).resolve()
        if not str(input_path).startswith(str(Path(OUTPUT_DIR).resolve())):
            return {
                "status": "error",
                "error": "Invalid filename: path escapes output directory",
            }
        if not input_path.exists():
            return {"status": "error", "error": f"Video file not found: {safe_filename}"}

        output_filename = f"{input_path.stem}.jpg"
        output_path = Path(OUTPUT_DIR) / output_filename

        # -ss before -i seeks at the container level (fast, may snap to keyframe).
        # For a DM reel thumbnail that's fine — we want a representative still,
        # not a specific frame. `-frames:v 1 -q:v 2` gives a high-quality JPEG.
        command = [
            "ffmpeg",
            "-ss", str(at_seconds),
            "-i", str(input_path),
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=60)

        if not output_path.exists() or output_path.stat().st_size == 0:
            return {
                "status": "error",
                "error": "ffmpeg produced no output (video shorter than at_seconds?)",
            }

        return {
            "status": "success",
            "filename": output_filename,
            "path": str(output_path),
            "at_seconds": at_seconds,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": f"ffmpeg failed: {e.stderr.decode() if e.stderr else str(e)}",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def cleanup_files(
    retention_days: Annotated[Optional[int], "Retention period in days (minimum 1). Defaults to CLEANUP_RETENTION_DAYS env var."] = None,
) -> dict:
    """[media] Manually trigger cleanup of old video files older than the retention period.

    Call only if the user explicitly requests file cleanup — retention is managed automatically.

    Args:
        retention_days: Retention period in days (minimum 1, default from CLEANUP_RETENTION_DAYS env)

    Returns:
        Dictionary with status and number of files deleted
    """
    try:
        # Enforce minimum retention to prevent accidental deletion of all files
        if retention_days is not None and retention_days < 1:
            return {
                "status": "error",
                "error": "retention_days must be at least 1 to prevent accidental deletion of all files"
            }
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


from datetime import datetime, timezone as _tz  # noqa: E402
from starlette.requests import Request as _SReq  # noqa: E402
from starlette.responses import FileResponse as _FResp  # noqa: E402
from starlette.responses import JSONResponse as _SResp  # noqa: E402

_start_time = datetime.now(_tz.utc)


def _resolve_version() -> str:
    # Release CI bumps pyproject.toml but NOT src/mcp_ytdlp/__init__.py,
    # so the installed-package metadata is the authoritative source.
    # Fall back to the source-file literal only if importlib.metadata
    # can't find the package (dev install / editable without reinstall).
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("mcp-ytdlp")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    try:
        from mcp_ytdlp import __version__ as _v

        return _v
    except ImportError:
        return "0.0.0"


_version = _resolve_version()


@mcp.custom_route("/health", methods=["GET"])
async def _health(request: _SReq) -> _SResp:
    return _SResp({
        "status": "healthy",
        "service": "mcp-ytdlp",
        "version": _version,
        "upstream_reachable": True,
        "uptime_seconds": int((datetime.now(_tz.utc) - _start_time).total_seconds()),
    })


@mcp.custom_route("/healthz", methods=["GET"])
async def _healthz(request: _SReq) -> _SResp:
    return await _health(request)


@mcp.custom_route("/files/{name}", methods=["GET"])
async def _get_file(request: _SReq):
    """Serve a downloaded file by plain filename.

    Authenticated with the same bearer token as the MCP protocol. Exists so
    callers (e.g. Bork) can pull the mp4 bytes after `download_video` without
    sharing the /data volume. The filename comes from the tool response, so
    clients must URL-encode it (yt-dlp replaces `?` with fullwidth `？` and
    other URL chars may appear in the `id` portion).
    """
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not _api_key or not hmac.compare_digest(token, _api_key):
        return _SResp({"error": "unauthorized"}, status_code=401)

    name = request.path_params.get("name", "")
    safe_name = Path(name).name
    if safe_name != name or ".." in name or "/" in name or "\\" in name:
        return _SResp({"error": "invalid filename"}, status_code=400)

    file_path = (Path(OUTPUT_DIR) / safe_name).resolve()
    if not str(file_path).startswith(str(Path(OUTPUT_DIR).resolve())):
        return _SResp({"error": "path escapes output directory"}, status_code=400)
    if not file_path.exists() or not file_path.is_file():
        return _SResp({"error": "file not found"}, status_code=404)

    return _FResp(str(file_path), filename=safe_name)


def main():
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
