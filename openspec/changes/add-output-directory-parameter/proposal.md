# Change: Add Output Directory Parameter to Video and Screenshot Tools

## Why
Currently, the output directory for downloaded videos and extracted screenshots is configured via the `OUTPUT_DIRECTORY` environment variable, which requires container restart or environment reconfiguration to change. Adding an optional `output_directory` parameter to the `download_video` and `extract_screenshot` MCP tools allows dynamic selection of output directories per operation, providing greater flexibility without requiring environment variable changes or container restarts.

## What Changes
- Add optional `output_directory` parameter to `download_video` MCP tool
- Add optional `output_directory` parameter to `extract_screenshot` MCP tool
- When `output_directory` is provided, use it instead of the `OUTPUT_DIRECTORY` environment variable
- When `output_directory` is not provided, fall back to `OUTPUT_DIRECTORY` environment variable (maintains backward compatibility)
- Ensure the specified output directory exists before writing files (create if needed)
- Update function implementations to support dynamic output directory selection

## Impact
- Affected specs: `media-processing` capability (MODIFIED requirements)
- Affected code:
  - `dist/main.py` - `download_video()` and `extract_screenshot()` functions
- Breaking changes: None (backward compatible - parameter is optional)
- Migration: No migration needed - existing behavior preserved when parameter is not provided

