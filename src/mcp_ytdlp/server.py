#!/usr/bin/env python3
"""
Media Processing Sidecar Service
FastMCP server for video download, conversion, and cleanup
"""

import hmac
import subprocess
import uuid
import threading
import time
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Annotated, Literal, Optional, Any, Dict, Tuple

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .auth import BearerTokenVerifier
from .config import settings

OUTPUT_DIR = settings.output_directory
CLEANUP_RETENTION_DAYS = settings.cleanup_retention_days
VIDEO_FILENAME_FORMAT = settings.video_filename_format

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


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


_api_key = settings.mcp_api_key.get_secret_value()
_auth = BearerTokenVerifier(api_key=_api_key) if _api_key else None

SERVER_INSTRUCTIONS = """\
Media Processing Sidecar — download videos with yt-dlp, transcode with FFmpeg,
and reclaim disk space on a retention schedule.

File lifecycle:
  1. download_video(url) fetches a video into the server's output directory and
     returns its `filename` plus curated metadata. Pass an optional `convert_to`
     to download and transcode in a single call.
  2. Fetch the bytes over HTTP at GET /files/{filename} using the same bearer
     token (URL-encode the filename — yt-dlp emits unicode chars in some ids).
  3. convert_video(filename, target_format) re-encodes a file already in the
     output directory to mp4/webm/avi/mov/mkv.
  4. Files auto-expire after the retention window (default 7 days); a background
     thread sweeps hourly. cleanup_files is a manual override — only call it when
     the user explicitly asks to free space.

Choosing a tool:
  - "download / grab / save this video"  -> download_video
  - "download it as webm/mp4/..."         -> download_video(convert_to=...)
  - "convert / re-encode an existing file" -> convert_video
  - "clean up / delete old downloads"      -> cleanup_files (destructive)

Reference data (no tool call needed) is exposed as resources:
  ytdlp://formats, ytdlp://retention, ytdlp://version, ytdlp://config.
For authenticated (private/age-restricted) videos, supply a Netscape-format
cookies file placed in the output directory; see the `authenticated_download`
prompt.
"""

# Initialize FastMCP server
mcp = FastMCP("Media Processing Sidecar", auth=_auth, instructions=SERVER_INSTRUCTIONS)

# Progress tracking storage (in-memory, keyed by task ID)
progress_store = {}

# Cache for yt-dlp version info (check once per hour)
_version_cache = {"version": None, "latest_version": None, "update_available": None, "last_check": None}


class _DictCompatModel(BaseModel):
    """Pydantic base that still supports legacy ``result["key"]`` access.

    The tools historically returned plain dicts and both the existing live
    clients (Bork, MCP portal) and this repo's test suite read fields via
    subscription (``res["status"]``, ``res["filename"]``). Returning typed
    models gives fastmcp a real ``output_schema`` without breaking any of
    that — the model behaves like a read-only mapping for the keys it
    declares plus any extra fields it carries.
    """

    model_config = {"extra": "allow"}

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as exc:  # pragma: no cover - mirrors dict KeyError
            raise KeyError(key) from exc

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.model_dump(exclude_none=True)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class VideoMetadata(_DictCompatModel):
    """Curated subset of yt-dlp metadata (the ~15 fields clients actually use)."""

    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    thumbnails: list[Any] = Field(default_factory=list)
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None
    channel: Optional[str] = None
    channel_id: Optional[str] = None
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    webpage_url: Optional[str] = None


class DownloadResult(_DictCompatModel):
    """Structured result of a successful download_video call."""

    status: Literal["success"] = "success"
    filename: str = Field(description="Plain filename in the output directory; fetch at /files/{filename}")
    path: str = Field(description="Absolute path of the written file on the server")
    metadata: Optional[VideoMetadata] = Field(
        default=None, description="Curated video metadata, when extraction succeeded"
    )
    converted_to: Optional[str] = Field(
        default=None, description="Target format if the file was transcoded in the same call"
    )


class ConvertResult(_DictCompatModel):
    """Structured result of a successful convert_video call."""

    status: Literal["success"] = "success"
    filename: str = Field(description="Filename of the transcoded output in the output directory")
    path: str = Field(description="Absolute path of the transcoded file on the server")
    target_format: Optional[str] = Field(default=None, description="Container the file was converted to")


class CleanupResult(_DictCompatModel):
    """Structured result of a cleanup_files call."""

    status: Literal["success"] = "success"
    files_deleted: int = Field(description="Number of expired video files removed")
    retention_days: int = Field(description="Retention window applied for this sweep")


class ErrorResult(_DictCompatModel):
    """Backward-compatible error envelope ({'status': 'error', ...}).

    Kept as the failure shape (rather than raising ToolError) so existing
    clients and tests that branch on ``res['status'] == 'error'`` keep working.
    """

    status: Literal["error"] = "error"
    error: str
    url: Optional[str] = None


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


def _emit(ctx: Optional["Context"], message: str) -> None:
    """Best-effort ctx.info() that is safe to call from sync tool bodies.

    fastmcp's ``ctx.info`` is a coroutine. The tools here stay synchronous so
    that direct (non-MCP) callers and the test suite can invoke them without an
    event loop. When a loop *is* running (the normal MCP server path) we schedule
    the log; otherwise we no-op. Logging must never break a download.
    """
    if ctx is None:
        return
    try:
        import asyncio

        coro = ctx.info(message)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(coro)
        else:  # no loop: close the coroutine to avoid "never awaited" warnings
            coro.close()
    except Exception:
        pass


def _emit_progress(
    ctx: Optional["Context"], progress: float, total: float, message: str = ""
) -> None:
    """Best-effort ctx.report_progress() mirroring :func:`_emit`'s loop handling."""
    if ctx is None:
        return
    try:
        import asyncio

        coro = ctx.report_progress(progress=progress, total=total, message=message)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(coro)
        else:
            coro.close()
    except Exception:
        pass


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


@mcp.tool(
    annotations=ToolAnnotations(
        title="Download video (yt-dlp)",
        readOnlyHint=False,      # writes a file into the output directory
        destructiveHint=False,   # only creates new files, never deletes
        idempotentHint=True,     # re-downloading the same URL converges on the same file
        openWorldHint=True,      # reaches external sites over the network
    )
)
def download_video(
    url: Annotated[str, "Video URL to download (YouTube, Vimeo, etc.)"],
    cookies_file: Optional[str] = None,
    output_directory: Optional[str] = None,
    convert_to: Annotated[
        Optional[Literal["mp4", "webm", "avi", "mov", "mkv"]],
        "Optionally transcode the download to this container in the same call (e.g. 'download as webm')",
    ] = None,
    ctx: Context | None = None,
) -> DownloadResult | ErrorResult:
    """[media] Download a video from a URL using yt-dlp.

    Args:
        url: Video URL to download
        cookies_file: Optional path to cookies file for authentication
        output_directory: Optional output directory path. Defaults to OUTPUT_DIRECTORY env var or /data.
        convert_to: Optional target container (mp4/webm/avi/mov/mkv). When set, the
            downloaded file is transcoded with FFmpeg before returning, so a single
            "download this as webm" intent resolves in one call.

    Returns:
        DownloadResult on success (status/filename/path/metadata, plus converted_to
        when convert_to was set); ErrorResult ({'status': 'error', ...}) on failure.
    """
    try:
        print(f"[download_video] Request received")
        print(f"[download_video] URL: {url}")
        _emit(ctx, f"download_video: validating {url}")
        _emit_progress(ctx, 0, 100, "validating")

        try:
            _validate_url(url)
        except ValueError as e:
            return ErrorResult(error=str(e), url=url)

        # Clean up cookies_file value
        if cookies_file in ("[null]", "null", ""):
            cookies_file = None

        if cookies_file:
            print("[download_video] cookies_file provided")
            try:
                cookies_file = str(_validate_cookies_path(cookies_file))
            except ValueError as e:
                return ErrorResult(error=str(e), url=url)

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

        _emit(ctx, "extracting metadata")
        _emit_progress(ctx, 10, 100, "extracting metadata")
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
            _emit(ctx, f"metadata extraction failed: {error_msg}")
            return ErrorResult(error=error_msg, url=url)
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

        # Build yt-dlp command for download. ``--print after_move:filepath``
        # is the only reliable way to identify the file yt-dlp actually
        # wrote: scanning the output dir for "most recently modified" can
        # silently return a stale file from a previous call when yt-dlp's
        # current download no-ops (existing-file skip, partial fail with
        # exit 0, etc.). yt-dlp 2023.07.06+ supports the flag; older
        # versions ignore it and the snapshot-diff fallback below catches
        # the new file that way.
        command = [
            "yt-dlp",
            "--format", "best[ext=mp4]",
            "--output", output_template,
            "--no-playlist",
            "--print", "after_move:filepath",
            "--no-simulate",  # --print would otherwise suppress the actual download
        ]

        # Add cookies file if provided
        if cookies_file and cookies_file != "[null]":
            command.extend(["--cookies", cookies_file])

        command.append(url)

        # Snapshot existing files BEFORE download so we can detect the
        # new file deterministically even on yt-dlp versions that don't
        # honor ``--print after_move:filepath`` (it's a no-op there
        # rather than an error).
        output_path = output_dir_path
        if not output_path.exists():
            raise Exception(f"Output directory does not exist: {output_dir}")

        existing = {p.name for p in output_path.iterdir() if p.is_file()}

        print(f"[download_video] Starting download")
        _emit(ctx, f"downloading {metadata.get('title') if metadata else url}")
        _emit_progress(ctx, 30, 100, "downloading")
        # Run yt-dlp to download
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        video_extensions = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv", ".m4v"}
        downloaded: Optional[Path] = None

        # Preferred: trust the path yt-dlp printed via ``--print after_move:filepath``.
        # The flag prints exactly one line per processed video — the final path
        # after any post-processing / move. We still verify it on disk.
        for line in reversed((result.stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            candidate = Path(line)
            if candidate.suffix.lower() in video_extensions and candidate.exists():
                downloaded = candidate
                break

        # Fallback for older yt-dlp: find the file that didn't exist before.
        if downloaded is None:
            new_files = [
                p for p in output_path.iterdir()
                if p.is_file() and p.name not in existing
            ]
            video_new = [p for p in new_files if p.suffix.lower() in video_extensions]
            if video_new:
                video_new.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                downloaded = video_new[0]

        # Last-resort fallback: most-recent video in the dir, BUT only if
        # yt-dlp's stdout had any signal of actual work. If yt-dlp clearly
        # didn't write anything (no after_move and no new file), it's
        # safer to fail loudly than to return a stale neighbor.
        if downloaded is None:
            raise Exception(
                "yt-dlp reported success but produced no new file in the output directory. "
                "This usually indicates a silent format mismatch or expired signed URL."
            )

        print(f"[download_video] Download complete: {downloaded.name}")
        _emit(ctx, f"download complete: {downloaded.name}")
        most_recent = downloaded

        # Curated metadata (kept identical to the historical dict shape).
        meta_model: Optional[VideoMetadata] = None
        if metadata:
            meta_model = VideoMetadata(
                id=metadata.get("id"),
                title=metadata.get("title"),
                description=metadata.get("description"),
                duration=metadata.get("duration"),
                thumbnail=metadata.get("thumbnail"),
                thumbnails=metadata.get("thumbnails", []),
                uploader=metadata.get("uploader"),
                uploader_id=metadata.get("uploader_id"),
                channel=metadata.get("channel"),
                channel_id=metadata.get("channel_id"),
                upload_date=metadata.get("upload_date"),
                view_count=metadata.get("view_count"),
                like_count=metadata.get("like_count"),
                webpage_url=metadata.get("webpage_url"),
            )

        # Optional one-call transcode ("download this as webm").
        if convert_to and most_recent.suffix.lower().lstrip(".") != convert_to:
            _emit(ctx, f"converting to {convert_to}")
            _emit_progress(ctx, 80, 100, f"converting to {convert_to}")
            conv = _convert_file(most_recent.name, convert_to)
            if isinstance(conv, ErrorResult):
                return conv
            _emit_progress(ctx, 100, 100, "done")
            return DownloadResult(
                filename=conv.filename,
                path=conv.path,
                metadata=meta_model,
                converted_to=convert_to,
            )

        _emit_progress(ctx, 100, 100, "done")
        return DownloadResult(
            filename=most_recent.name,
            path=str(most_recent),
            metadata=meta_model,
            converted_to=convert_to if convert_to else None,
        )

    except subprocess.CalledProcessError as e:
        error_msg = parse_ytdlp_error(e.stderr, url if 'url' in locals() else "unknown URL")
        print(f"[download_video] Download failed: {error_msg}")
        _emit(ctx, f"download failed: {error_msg}")
        return ErrorResult(error=error_msg, url=url if 'url' in locals() else None)
    except Exception as e:
        print(f"[download_video] Unexpected error: {e}")
        _emit(ctx, f"unexpected error: {e}")
        return ErrorResult(error=str(e))


ALLOWED_FORMATS = ("mp4", "webm", "avi", "mov", "mkv")
CODEC_MAP = {
    "mp4": ("-c:v", "libx264", "-c:a", "aac"),
    "webm": ("-c:v", "libvpx-vp9", "-c:a", "libopus"),
    "avi": ("-c:v", "libx264", "-c:a", "aac"),
    "mov": ("-c:v", "libx264", "-c:a", "aac"),
    "mkv": ("-c:v", "libx264", "-c:a", "aac"),
}


def _convert_file(
    video_filename: str,
    target_format: str,
    ctx: Optional["Context"] = None,
):
    """Transcode a file already in OUTPUT_DIR. Returns ConvertResult | ErrorResult.

    Shared by the ``convert_video`` tool and ``download_video``'s optional
    ``convert_to`` fusion so both paths apply identical traversal-guarding and
    codec selection.
    """
    try:
        # Path traversal protection: strip any directory components
        safe_filename = Path(video_filename).name
        if safe_filename != video_filename or ".." in video_filename:
            return ErrorResult(
                error="Invalid filename: must be a plain filename without path separators"
            )

        input_path = (Path(OUTPUT_DIR) / safe_filename).resolve()
        # Verify resolved path is still inside OUTPUT_DIR
        if not str(input_path).startswith(str(Path(OUTPUT_DIR).resolve())):
            return ErrorResult(error="Invalid filename: path escapes output directory")

        if not input_path.exists():
            return ErrorResult(error=f"Video file not found: {safe_filename}")

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

        _emit(ctx, f"transcoding {safe_filename} -> {target_format}")
        # Run FFmpeg with timeout to prevent indefinite blocking
        subprocess.run(command, check=True, capture_output=True, timeout=600)
        _emit(ctx, f"transcode complete: {output_filename}")

        return ConvertResult(
            filename=output_filename,
            path=str(output_path),
            target_format=target_format,
        )

    except subprocess.CalledProcessError as e:
        return ErrorResult(
            error=f"Conversion failed: {e.stderr.decode() if e.stderr else str(e)}"
        )
    except Exception as e:
        return ErrorResult(error=str(e))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Convert video format (FFmpeg)",
        readOnlyHint=False,      # writes a new transcoded file
        destructiveHint=False,   # creates a sibling file; leaves the source intact
        idempotentHint=True,     # re-running overwrites to the same output (-y)
        openWorldHint=False,     # local FFmpeg only, no network
    )
)
def convert_video(
    video_filename: Annotated[str, "Name of the video file in the output directory (filename only, no path)"],
    target_format: Literal["mp4", "webm", "avi", "mov", "mkv"],
    ctx: Context | None = None,
) -> ConvertResult | ErrorResult:
    """[media] Convert a video file to a different format using FFmpeg.

    Args:
        video_filename: Name of the video file to convert (must be in the output directory)
        target_format: Target format — mp4, webm, avi, mov, or mkv

    Returns:
        ConvertResult on success (status/filename/path); ErrorResult on failure.
    """
    return _convert_file(video_filename, target_format, ctx=ctx)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Clean up expired downloads",
        readOnlyHint=False,
        destructiveHint=True,    # permanently deletes files
        idempotentHint=False,    # what's deleted depends on age at call time
        openWorldHint=False,
    )
)
def cleanup_files(
    retention_days: Annotated[Optional[int], "Retention period in days (minimum 1). Defaults to CLEANUP_RETENTION_DAYS env var."] = None,
) -> CleanupResult | ErrorResult:
    """[media] Manually trigger cleanup of old video files older than the retention period.

    Call only if the user explicitly requests file cleanup — retention is managed automatically.

    Args:
        retention_days: Retention period in days (minimum 1, default from CLEANUP_RETENTION_DAYS env)

    Returns:
        CleanupResult on success (status/files_deleted/retention_days); ErrorResult on failure.
    """
    try:
        # Enforce minimum retention to prevent accidental deletion of all files
        if retention_days is not None and retention_days < 1:
            return ErrorResult(
                error="retention_days must be at least 1 to prevent accidental deletion of all files"
            )
        deleted_count = cleanup_old_files(retention_days)
        return CleanupResult(
            files_deleted=deleted_count,
            retention_days=retention_days or CLEANUP_RETENTION_DAYS,
        )
    except Exception as e:
        return ErrorResult(error=str(e))


# ---------------------------------------------------------------------------
# Resources — reference data the model can read without spending a tool call.
# ---------------------------------------------------------------------------


@mcp.resource(
    "ytdlp://formats",
    name="Supported target formats",
    description="Containers convert_video / download_video(convert_to=...) can produce, with codecs.",
    mime_type="application/json",
)
def _resource_formats() -> str:
    """Supported transcode targets and the FFmpeg codecs used for each."""
    return json.dumps(
        {
            "target_formats": list(ALLOWED_FORMATS),
            "codecs": {
                fmt: {"video": codecs[1], "audio": codecs[3]}
                for fmt, codecs in CODEC_MAP.items()
            },
            "download_default": "best[ext=mp4]",
            "note": "download_video always fetches mp4; pass convert_to to transcode in one call.",
        },
        indent=2,
    )


@mcp.resource(
    "ytdlp://retention",
    name="Retention policy",
    description="File lifecycle and auto-cleanup behavior for the output directory.",
    mime_type="application/json",
)
def _resource_retention() -> str:
    """Current retention window and how the auto-cleanup sweep behaves."""
    return json.dumps(
        {
            "retention_days": CLEANUP_RETENTION_DAYS,
            "swept_extensions": sorted(
                {".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv", ".m4v"}
            ),
            "sweep_interval": "hourly (background thread)",
            "manual_override": "cleanup_files(retention_days=...) — minimum 1 day",
            "basis": "file ctime older than now - retention_days is deleted",
        },
        indent=2,
    )


@mcp.resource(
    "ytdlp://version",
    name="yt-dlp version info",
    description="Installed yt-dlp version and whether a newer release is on PyPI (cached ~1h).",
    mime_type="application/json",
)
def _resource_version() -> str:
    """Installed vs latest yt-dlp version (reuses the hourly cache)."""
    return json.dumps(get_ytdlp_version_info(), indent=2)


@mcp.resource(
    "ytdlp://config",
    name="Server configuration",
    description="Non-secret runtime configuration (output dir, filename template, transport).",
    mime_type="application/json",
)
def _resource_config() -> str:
    """Effective non-secret configuration for this server instance."""
    return json.dumps(
        {
            "output_directory": OUTPUT_DIR,
            "cleanup_retention_days": CLEANUP_RETENTION_DAYS,
            "video_filename_format": VIDEO_FILENAME_FORMAT,
            "transport": settings.transport,
            "file_fetch_route": "GET /files/{filename} (bearer auth, URL-encode the name)",
            "auth_required": bool(_api_key),
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Prompts — guided multi-step workflows for this server's signature jobs.
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="download_and_convert",
    description="Guided workflow: download a video and (optionally) transcode it to a target format.",
    tags={"media", "workflow"},
)
def download_and_convert_prompt(
    url: str = Field(description="The video URL to download."),
    target_format: str = Field(
        default="",
        description="Optional target container (mp4/webm/avi/mov/mkv). Leave empty to keep mp4.",
    ),
) -> str:
    """Worked path for the common download-then-convert job."""
    fmt = (target_format or "").strip().lower()
    if fmt and fmt in ALLOWED_FORMATS:
        return (
            f"Download the video at {url} and deliver it as {fmt}.\n\n"
            f"Use a single call: download_video(url='{url}', convert_to='{fmt}'). "
            "That downloads and transcodes in one step and returns the final "
            "filename plus metadata. Then the bytes are available at "
            "GET /files/{filename} using the server bearer token (URL-encode the "
            "filename). Do not call cleanup_files unless the user asks to free space."
        )
    return (
        f"Download the video at {url}.\n\n"
        f"1. Call download_video(url='{url}'). Inspect the returned `filename` and "
        "`metadata` (title, uploader, duration).\n"
        "2. If the user later wants a different container, call "
        "convert_video(video_filename=<filename>, target_format=<mp4|webm|avi|mov|mkv>).\n"
        "3. Fetch bytes at GET /files/{filename} with the bearer token (URL-encode "
        "the filename). Leave retention to the automatic sweep."
    )


@mcp.prompt(
    name="authenticated_download",
    description="Guided workflow for downloading private / age-restricted videos using a cookies file.",
    tags={"media", "auth"},
)
def authenticated_download_prompt(
    url: str = Field(description="The private or age-restricted video URL."),
    cookies_file: str = Field(
        default="cookies.txt",
        description="Plain filename of a Netscape-format cookies file placed in the output directory.",
    ),
) -> str:
    """Worked path for auth-gated downloads via a cookies file."""
    return (
        f"The video at {url} likely requires sign-in (private, age-restricted, or "
        "members-only).\n\n"
        f"1. Ensure a Netscape-format cookies export named '{cookies_file}' exists in "
        "the server's output directory (it must be a plain filename — no path "
        "separators or .. — for the traversal guard to accept it).\n"
        f"2. Call download_video(url='{url}', cookies_file='{cookies_file}').\n"
        "3. If it still fails, read the ErrorResult.error message — it classifies the "
        "cause (private / age-restricted / geoblocked / auth-required) with the next "
        "step. Refresh the cookies export if authentication is rejected."
    )


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
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
