# mcp-ytdlp

[![PyPI](https://img.shields.io/pypi/v/mcp-ytdlp)](https://pypi.org/project/mcp-ytdlp/)

An MCP server that downloads videos with [yt-dlp](https://github.com/yt-dlp/yt-dlp), converts them with FFmpeg, and cleans up old files. It is meant for people who want an AI assistant (Claude, or any MCP client) to fetch and transcode media on a server they control, over HTTP or stdio. Built on [FastMCP](https://gofastmcp.com) 4.

## Requirements

- Python 3.10 or newer
- FastMCP 4 (`fastmcp>=4.0.10,<5.0.0`, installed as a dependency)
- FFmpeg on the `PATH` (the Docker image includes it)
- No upstream account. Private or age-restricted videos need a cookies file exported from your browser (see [Cookies](#cookies)).

## Install and run

### Local

```bash
pip install mcp-ytdlp        # or: uvx mcp-ytdlp
MCP_API_KEY=change-me OUTPUT_DIRECTORY=./data mcp-ytdlp
```

This starts a streamable HTTP server on `127.0.0.1:8000`, with the MCP endpoint at `/mcp`. For a local stdio client, set `TRANSPORT=stdio` (no API key needed).

### Docker

The image builds from source:

```bash
export MCP_API_KEY=change-me
docker compose up -d --build
```

`docker-compose.yaml` publishes the server on host port `8718` (override with `HOST_PORT`) and stores files in the `ytdlp_output` volume (override with `OUTPUT_HOST_DIR`). It also mounts the host directory `/opt/secrets/ytdlp` read-only at `/run/secrets` for the cookies file; if that directory is missing, Docker creates it empty and the server runs without cookies. The container exposes `/health` for health checks.

## Configuration

All settings are environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_API_KEY` | none | Bearer token clients must send. Required when `TRANSPORT=http`; the server refuses to start without it. |
| `TRANSPORT` | `http` | `http` (streamable HTTP) or `stdio` |
| `HOST` | `127.0.0.1` | Bind address (the Docker image sets `0.0.0.0`) |
| `PORT` | `8000` | Bind port |
| `OUTPUT_DIRECTORY` | `/data` | Where downloads and conversions are written |
| `CLEANUP_RETENTION_DAYS` | `7` | Downloads and job records older than this many days are deleted at startup and by the hourly sweep (minimum 1) |
| `YTDLP_COOKIES_FILE` | `/run/secrets/yt-cookies.txt` | Netscape-format cookies used for every download when the file exists and is readable. Empty disables it. See [Cookies](#cookies) |
| `VIDEO_FILENAME_FORMAT` | `%(extractor_key)s-%(id).60s.%(ext)s` | yt-dlp output template, for example `%(title).100s.%(ext)s` |
| `DOWNLOAD_TIMEOUT_SECONDS` | `1800` | Hard cap per yt-dlp subprocess |

The default filename template caps the id at 60 characters so that long signed CDN URLs do not exceed filesystem name limits.

## Authentication

Over HTTP every MCP request, and every `GET /files/{filename}` request, must carry `Authorization: Bearer <MCP_API_KEY>`. The token is compared in constant time. Put the server behind your own gateway or reverse proxy if you need anything beyond a shared key.

Example client entry:

```json
{
  "mcpServers": {
    "ytdlp": {
      "url": "http://localhost:8718/mcp",
      "headers": { "Authorization": "Bearer change-me" }
    }
  }
}
```

## Tools

| Tool | What it does |
| --- | --- |
| `download_video` | Download a URL with yt-dlp, optionally transcoding it in the same call (`convert_to`: mp4, webm, avi, mov, mkv). Starts a job and waits up to 20 s. |
| `get_download_result` | Long-poll a download that `download_video` returned as pending. Read-only. |
| `convert_video` | Transcode a file in the output directory with FFmpeg (`video_filename`, `target_format`: mp4, webm, avi, mov, mkv). |
| `cleanup_files` | Delete files older than the retention window now (`retention_days`, minimum 1). Marked destructive; the hourly sweep normally handles this. |

### Downloads: job and poll

Downloads often take longer than a client or proxy will hold a request open, so `download_video` runs the download on a worker thread and waits at most 20 seconds:

1. Call `download_video` with `url` (and optionally `cookies_file`, `output_directory`, `convert_to`).
2. If it finishes within 20 s, you get the result directly:
   ```json
   {"status": "success", "filename": "Youtube-dQw4w9WgXcQ.mp4", "path": "/data/Youtube-dQw4w9WgXcQ.mp4", "metadata": {"title": "...", "duration": 212}}
   ```
3. Otherwise you get a job handle, and the download keeps running:
   ```json
   {"job_id": "3f2a...", "status": "pending", "poll_with": {"tool": "get_download_result", "wait_seconds": 20}}
   ```
4. Call `get_download_result` with that `job_id` (and optionally `wait_seconds`, max 20). It returns the same pending handle until the download is done, then the success result. Repeat until `status` is `success`.

A failed download raises a tool error at whichever call observes it. Each job is also written to `OUTPUT_DIRECTORY/.jobs/<job_id>.json` (status, result or error, timestamps), so `get_download_result` still answers after a restart or redeploy. A download that was running when the server stopped is reported as a tool error: "Download was interrupted by a restart, start the download again". A `job_id` that was never issued, or whose record has passed the retention window, raises an "Unknown job_id" tool error.

`cookies_file` is a plain filename of a cookies file placed in the output directory; a server-wide cookies file takes precedence over it (see [Cookies](#cookies)). `output_directory` is a subdirectory of the output directory; paths that resolve outside it are rejected. The success result includes video metadata (title, uploader, duration, thumbnails, counts) and, when `convert_to` was set, `converted_to`.

To fetch the file bytes without sharing the volume, request `GET /files/{filename}` with the bearer token, URL-encoding the filename from the tool result.

### Retention

At startup and then every hour, the server deletes files older than `CLEANUP_RETENTION_DAYS` (default 7, by file ctime) anywhere under `OUTPUT_DIRECTORY`, subfolders included: video files (`.mp4`, `.webm`, `.avi`, `.mov`, `.mkv`, `.flv`, `.m4v`), partial downloads (`.part`, `.ytdl`) and job records in `.jobs/`. Nothing else is touched, so a cookies file in the output directory stays, and nothing outside `OUTPUT_DIRECTORY` is ever deleted (symlinks are not followed). A failing sweep is logged and retried an hour later; it never stops the server. `cleanup_files` runs the same sweep on demand.

### Cookies

Set `YTDLP_COOKIES_FILE` (default `/run/secrets/yt-cookies.txt`) to a Netscape-format cookies export. When that file exists and is readable, every download uses it automatically; no tool argument is needed. Precedence: the server-wide file wins, and the `cookies_file` argument is then ignored. Without it, `cookies_file` works as before.

The server hands yt-dlp a private temporary copy (mode 0600, deleted after the download), because yt-dlp writes the cookie jar back to the file it is given; the original can therefore sit on a read-only mount. Cookie contents are never logged. Keep the file out of `OUTPUT_DIRECTORY`, which is usually backed up. With the bundled compose file, place it at `/opt/secrets/ytdlp/yt-cookies.txt` on the host, readable by the container user (uid 100).

### Errors

Every tool raises an MCP tool error (`isError: true`) on failure, with a message that says what went wrong (for example `Video is private: ...`). There is no `{"status": "error"}` payload.

### Resources and prompts

- `ytdlp://formats`: supported transcode targets and codecs
- `ytdlp://retention`: retention window and sweep cadence
- `ytdlp://version`: installed yt-dlp version and whether a newer release exists
- `ytdlp://config`: non-secret runtime configuration
- Prompts: `download_and_convert`, `authenticated_download`

### Usage telemetry

A small middleware (`usage.py`) writes one JSON line per tool call to stderr with the server name, tool name, duration, outcome and protocol version. It never logs arguments or results.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

CI (`.github/workflows/ci.yml`) runs lint and tests as the `test` check on every pull request. `main` is protected and changes land through pull requests.

## Releases

Releases are tag-only. After a merge to `main`, the release workflow tests the code and pushes the next `v*` patch tag; nothing is committed back to `main`. The tag triggers the PyPI publish, and the wheel takes its version from the tag. Do not bump `version` in `pyproject.toml` by hand.

## Support

If this server saves you time, you can [buy me a coffee](https://buymeacoffee.com/caseyberlin).

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Casey Romkes.
