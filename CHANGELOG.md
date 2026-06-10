# Changelog

## [0.2.16] - 2026-06-10

- feat: fastmcp 3.4.2 uplift — annotations, structured output, resources, prompts, context (#16)


## [0.2.14] - 2026-05-07

- ops(docker): add log rotation (10m/3 files) to cap unbounded json-file logs


## [0.2.13] - 2026-05-04

- fix(download_video): identify written file by stdout/snapshot, not mtime


## [0.2.12] - 2026-05-04

- fix(download_video): identify the just-written file via `--print after_move:filepath` + before/after directory snapshot, instead of "most recently modified file in output dir". The old logic would silently return a stale neighbor (a previous download's bytes) when yt-dlp's current download no-opped — caller saw the wrong video file for a successful-looking response. Now raises loudly if no new file is produced.


## [0.2.11] - 2026-04-20

- revert(frame): drop extract_frame tool


## [0.2.9] - 2026-04-20

- feat(frame): extract_frame tool + resolve /health version from metadata


## [0.2.8] - 2026-04-20

- feat(files): add GET /files/{name} so HTTP clients can fetch downloads


## [0.2.7] - 2026-04-20

- fix(compose): match new default output template with the code


## [0.2.6] - 2026-04-20

- fix(filename): cap id to 60 chars to avoid Errno 36 on CDN URLs


## [0.2.5] - 2026-04-20

- fix(filename): cap id to 60 chars in the default output template.
  The generic extractor uses the full source URL as `id`, which for
  signed CDN URLs (300+ chars) tripped Errno 36 "File name too long"
  on ext4/APFS. Template is now `%(extractor_key)s-%(id).60s.%(ext)s`.

## [0.2.4] - 2026-04-19

- fix(security): validate URL schemes and cookies_file paths


## [0.2.3] - 2026-04-18

- feat(reliability): stateless_http + /health + fail-fast + FastMCP 3.2.4


## [0.2.2] - 2026-04-09

- fix: lowercase Docker image tags in release CI


## [0.2.0] - 2026-04-09

### Changed
- Bumped FastMCP dependency to >=3.2.2
- Added explicit user-confirmation guidance to cleanup_files docstring

### Added
- Automated version bump and release CI via GitHub Actions

## [0.1.0] - 2026-01-01
### Added
- Initial release: FastMCP server wrapping yt-dlp
- `download_video` tool: download video with metadata and thumbnails
- `convert_video` tool: convert between formats (mp4, webm, avi, mov) via FFmpeg
- `cleanup_files` tool: manual cleanup of old downloaded files
- HTTP transport with configurable host/port
- Automatic yt-dlp version checking against PyPI
