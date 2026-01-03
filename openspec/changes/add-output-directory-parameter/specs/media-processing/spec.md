## MODIFIED Requirements

### Requirement: Video Download MCP Tool
The system SHALL provide an MCP tool to download videos from URLs using yt-dlp.

#### Scenario: Successful video download via MCP
- **WHEN** an MCP client calls the download tool with a valid video URL
- **THEN** the video is downloaded to the shared storage volume
- **AND** the tool returns a success response with the filename and path
- **AND** the video file is in MP4 format (or best available MP4-compatible format)

#### Scenario: Download failure handling
- **WHEN** an MCP client calls the download tool with an invalid or inaccessible URL
- **THEN** the tool returns an error response with a descriptive error message

#### Scenario: Configurable filename format
- **WHEN** `VIDEO_FILENAME_FORMAT` environment variable is set with yt-dlp formatting syntax
- **THEN** downloaded videos use the specified format for filenames
- **AND** format supports yt-dlp variables (e.g., `%(title)s`, `%(id)s`, `%(ext)s`)

#### Scenario: Default filename format
- **WHEN** `VIDEO_FILENAME_FORMAT` environment variable is not set
- **THEN** videos use a default unique filename format to prevent collisions

#### Scenario: Cookies file authentication
- **WHEN** an MCP client calls the download tool with an optional cookies file path
- **THEN** yt-dlp uses the cookies file for authentication
- **AND** the download proceeds with authenticated session (e.g., for age-restricted or private content)

#### Scenario: Progress tracking during download
- **WHEN** a video download is in progress
- **THEN** progress updates are available to the MCP client
- **AND** the progress includes percentage complete and download speed

#### Scenario: Dynamic output directory
- **WHEN** an MCP client calls the download tool with an optional `output_directory` parameter
- **THEN** the video is downloaded to the specified directory
- **AND** the directory is created if it does not exist
- **AND** the tool returns a success response with the filename and path relative to the specified directory

#### Scenario: Output directory fallback
- **WHEN** an MCP client calls the download tool without the `output_directory` parameter
- **THEN** the video is downloaded to the directory specified by the `OUTPUT_DIRECTORY` environment variable
- **AND** if `OUTPUT_DIRECTORY` is not set, files are saved to the default directory `/data`

### Requirement: Screenshot Extraction MCP Tool
The system SHALL provide an MCP tool to extract a single frame from a video file at a specified timestamp.

#### Scenario: Successful screenshot extraction via MCP
- **WHEN** an MCP client calls the screenshot tool with a valid video filename and timestamp
- **THEN** a JPEG screenshot is created at the specified timestamp
- **AND** the screenshot is saved to the shared storage volume
- **AND** the tool returns a success response with the screenshot filename and path

#### Scenario: Screenshot failure handling
- **WHEN** an MCP client calls the screenshot tool with a non-existent video filename
- **THEN** the tool returns an error response with a descriptive error message

#### Scenario: Timestamp format support
- **WHEN** a timestamp is provided in HH:MM:SS format
- **THEN** the screenshot is extracted at the corresponding time position in the video

#### Scenario: Configurable screenshot filename format
- **WHEN** `SCREENSHOT_FILENAME_FORMAT` environment variable is set with formatting syntax
- **THEN** screenshot files use the specified format for filenames
- **AND** format supports variables (e.g., `%(video_filename)s`, `%(timestamp)s`)

#### Scenario: Default screenshot filename format
- **WHEN** `SCREENSHOT_FILENAME_FORMAT` environment variable is not set
- **THEN** screenshots use a default format (e.g., `{video_filename}_{timestamp}.jpg`)

#### Scenario: Dynamic output directory for screenshots
- **WHEN** an MCP client calls the screenshot tool with an optional `output_directory` parameter
- **THEN** the screenshot is saved to the specified directory
- **AND** the directory is created if it does not exist
- **AND** the tool returns a success response with the screenshot filename and path relative to the specified directory

#### Scenario: Screenshot output directory fallback
- **WHEN** an MCP client calls the screenshot tool without the `output_directory` parameter
- **THEN** the screenshot is saved to the directory specified by the `OUTPUT_DIRECTORY` environment variable
- **AND** if `OUTPUT_DIRECTORY` is not set, files are saved to the default directory `/data`

### Requirement: Shared Storage Access
The system SHALL provide shared file storage accessible to both the media-sidecar and n8n containers.

#### Scenario: Configurable output directory
- **WHEN** `OUTPUT_DIRECTORY` environment variable is set in docker-compose
- **THEN** downloaded videos, converted videos, and screenshots are saved to the specified directory by default
- **AND** the directory path is used for all file operations when no per-operation output directory is specified
- **AND** per-operation `output_directory` parameters override the environment variable setting

#### Scenario: Default output directory
- **WHEN** `OUTPUT_DIRECTORY` environment variable is not set
- **THEN** files are saved to the default directory `/data` (mapped from host `/mnt/data/AI/n8n`) when no per-operation output directory is specified

#### Scenario: File write and read
- **WHEN** the media-sidecar writes a file to the output directory
- **THEN** the file is immediately accessible to n8n at the same path
- **AND** n8n can read the file using its "Read Binary File" node

#### Scenario: Volume persistence
- **WHEN** containers are restarted
- **THEN** files in the shared volume persist (unless explicitly cleaned up)

#### Scenario: Dynamic directory creation
- **WHEN** an MCP client specifies an `output_directory` parameter that does not exist
- **THEN** the directory is created automatically with appropriate permissions
- **AND** the file operation proceeds successfully

