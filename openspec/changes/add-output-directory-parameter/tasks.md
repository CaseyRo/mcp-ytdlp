## 1. Implementation
- [x] 1.1 Add optional `output_directory` parameter to `download_video` function signature
- [x] 1.2 Update `download_video` to use `output_directory` parameter when provided, fallback to `OUTPUT_DIR` env var when not provided
- [x] 1.3 Ensure output directory exists in `download_video` (create if needed with appropriate permissions)
- [x] 1.4 Add optional `output_directory` parameter to `extract_screenshot` function signature
- [x] 1.5 Update `extract_screenshot` to use `output_directory` parameter when provided, fallback to `OUTPUT_DIR` env var when not provided
- [x] 1.6 Ensure output directory exists in `extract_screenshot` (create if needed with appropriate permissions)
- [x] 1.7 Update function docstrings to document the new `output_directory` parameter

## 2. Validation
- [ ] 2.1 Test `download_video` with `output_directory` parameter - verify file is saved to specified directory
- [ ] 2.2 Test `download_video` without `output_directory` parameter - verify backward compatibility (uses env var)
- [ ] 2.3 Test `extract_screenshot` with `output_directory` parameter - verify screenshot is saved to specified directory
- [ ] 2.4 Test `extract_screenshot` without `output_directory` parameter - verify backward compatibility (uses env var)
- [ ] 2.5 Test with non-existent output directory - verify directory is created automatically
- [ ] 2.6 Test with invalid output directory path - verify appropriate error handling
- [ ] 2.7 Verify that directory creation preserves existing behavior for default output directory

