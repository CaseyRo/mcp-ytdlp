# Changelog

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
