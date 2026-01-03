## ADDED Requirements

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

### Requirement: Video Conversion MCP Tool
The system SHALL provide an MCP tool to convert videos between formats using FFmpeg.

#### Scenario: Successful video conversion via MCP
- **WHEN** an MCP client calls the conversion tool with a valid video filename and target format
- **THEN** the video is converted to the specified format
- **AND** the converted video is saved to the shared storage volume
- **AND** the tool returns a success response with the output filename and path

#### Scenario: Conversion failure handling
- **WHEN** an MCP client calls the conversion tool with a non-existent video filename or unsupported format
- **THEN** the tool returns an error response with a descriptive error message

#### Scenario: Format support
- **WHEN** a target format is specified (e.g., mp4, webm, avi, mov)
- **THEN** FFmpeg converts the video to the requested format if supported
- **AND** the conversion preserves video quality and audio track

#### Scenario: Progress tracking during conversion
- **WHEN** a video conversion is in progress
- **THEN** progress updates are available to the MCP client
- **AND** the progress includes percentage complete and processing speed

### Requirement: Shared Storage Access
The system SHALL provide shared file storage accessible to both the media-sidecar and n8n containers.

#### Scenario: Configurable output directory
- **WHEN** `OUTPUT_DIRECTORY` environment variable is set in docker-compose
- **THEN** all downloaded videos, converted videos, and screenshots are saved to the specified directory
- **AND** the directory path is used for all file operations

#### Scenario: Default output directory
- **WHEN** `OUTPUT_DIRECTORY` environment variable is not set
- **THEN** files are saved to the default directory `/data` (mapped from host `/mnt/data/AI/n8n`)

#### Scenario: File write and read
- **WHEN** the media-sidecar writes a file to the output directory
- **THEN** the file is immediately accessible to n8n at the same path
- **AND** n8n can read the file using its "Read Binary File" node

#### Scenario: Volume persistence
- **WHEN** containers are restarted
- **THEN** files in the shared volume persist (unless explicitly cleaned up)

### Requirement: Container Orchestration
The system SHALL run the media-sidecar service alongside n8n using Docker Compose.

#### Scenario: Service startup
- **WHEN** docker-compose up is executed
- **THEN** both n8n and media-sidecar containers start successfully
- **AND** the media-sidecar MCP server is accessible to MCP clients

#### Scenario: MCP server availability via HTTP
- **WHEN** an MCP client connects to the media-sidecar service via HTTP
- **THEN** the client can discover and invoke available MCP tools (download, convert, screenshot, cleanup)
- **AND** the MCP protocol communication is established successfully over HTTP
- **AND** the service is accessible on port 8000

#### Scenario: Network accessibility
- **WHEN** an MCP client makes an HTTP request to the media-sidecar service
- **THEN** the service responds with valid MCP protocol messages
- **AND** the service is reachable from other containers on the Docker network
- **AND** the service is accessible via HTTP transport (not limited to stdio)

### Requirement: Automatic File Cleanup
The system SHALL automatically remove video files older than 7 days based on file creation date.

#### Scenario: Automatic cleanup execution
- **WHEN** files in the shared storage volume are older than 7 days (based on creation date)
- **THEN** those files are automatically deleted
- **AND** recently created files (within 7 days) are preserved

#### Scenario: Cleanup scope
- **WHEN** automatic cleanup runs
- **THEN** only video files are removed (based on file extension or type detection)
- **AND** screenshot files and other non-video files are preserved unless also older than 7 days

#### Scenario: Cleanup timing
- **WHEN** the service is running
- **THEN** cleanup runs periodically (e.g., daily or on service startup)
- **AND** cleanup does not interfere with active downloads or conversions

#### Scenario: Configurable retention period
- **WHEN** `CLEANUP_RETENTION_DAYS` environment variable is set in docker-compose
- **THEN** automatic cleanup uses the specified retention period (in days) instead of the default 7 days
- **AND** files older than the configured retention period are removed

#### Scenario: Default retention period
- **WHEN** `CLEANUP_RETENTION_DAYS` environment variable is not set
- **THEN** automatic cleanup uses the default retention period of 7 days

### Requirement: Manual Cleanup MCP Tool
The system SHALL provide an MCP tool to manually trigger cleanup operations.

#### Scenario: Manual cleanup execution
- **WHEN** an MCP client calls the manual cleanup tool
- **THEN** cleanup is executed immediately
- **AND** files older than the configured retention period are removed
- **AND** the tool returns a success response with the number of files deleted

#### Scenario: Manual cleanup with custom retention
- **WHEN** an MCP client calls the manual cleanup tool with an optional retention period parameter
- **THEN** cleanup removes files older than the specified retention period (overriding the environment variable setting)
- **AND** the cleanup operation completes successfully

### Requirement: User Documentation
The system SHALL provide comprehensive documentation for easy setup and usage.

#### Scenario: Quick start documentation
- **WHEN** a user reads the README.md file
- **THEN** they can follow step-by-step instructions to set up and run the service
- **AND** the documentation includes prerequisites, installation steps, and basic usage examples

#### Scenario: Configuration documentation
- **WHEN** a user wants to configure the service
- **THEN** the documentation explains all environment variables and their purposes
- **AND** the documentation provides examples of common configuration scenarios

#### Scenario: MCP tool usage documentation
- **WHEN** a user wants to use the MCP tools
- **THEN** the documentation describes each MCP tool with parameters, examples, and expected responses
- **AND** the documentation includes examples for connecting MCP clients (e.g., Claude Desktop)

#### Scenario: Troubleshooting documentation
- **WHEN** a user encounters issues
- **THEN** the documentation provides common problems and solutions
- **AND** the documentation includes debugging tips and log locations

