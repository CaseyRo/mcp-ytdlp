## Context
n8n workflows require video download and screenshot extraction capabilities. The solution must integrate seamlessly with existing n8n Docker deployments while maintaining isolation and stability. Video processing is CPU-intensive and can impact workflow orchestration if run directly in the n8n container.

## Goals / Non-Goals

### Goals
- Provide MCP (Model Context Protocol) server for video download, conversion, and screenshot extraction
- Enable direct LLM integration through standardized MCP protocol
- Isolate video processing from n8n workflow execution
- Enable file sharing between containers via shared volumes
- Support MP4 video format for compatibility
- Allow timestamp-based screenshot extraction
- Provide video format conversion and transcoding capabilities using FFmpeg
- Automatically clean up video files older than 7 days (based on file creation date)
- Provide progress tracking for long-running operations (downloads, conversions)
- Support cookies file authentication for yt-dlp (e.g., YouTube login)

### Non-Goals
- Video editing or manipulation beyond format conversion and frame extraction
- Traditional REST HTTP API (using MCP protocol instead)
- Support for video streaming or live processing
- Authentication/authorization (assumes trusted Docker network)

## Decisions

### Decision: Sidecar Pattern Over Custom n8n Image
**What**: Use a separate containerized microservice instead of extending the n8n Docker image.
**Why**:
- Prevents video processing from crashing n8n workflows
- Allows independent updates of n8n and media processing tools
- Simplifies maintenance and debugging
- Follows microservices best practices

**Alternatives considered**:
- Custom n8n Docker image: Would require rebuilding on every n8n update and mixing concerns
- Direct installation in n8n container: Would risk stability and complicate updates

### Decision: FastMCP for MCP Server with HTTP Transport
**What**: Use FastMCP framework to create an MCP (Model Context Protocol) server accessible via HTTP transport, ensuring network-based accessibility.
**Why**:
- Standardized protocol for LLM interactions
- Pythonic interface with minimal boilerplate
- Direct integration with LLMs and AI assistants
- Automatic tool exposure through decorators
- Better suited for AI/LLM workflows than REST APIs
- HTTP transport enables network-based access from any MCP client
- Allows access from remote clients, not just local processes
- Standard HTTP port (8000) for easy integration

**Alternatives considered**:
- FastAPI/HTTP REST: Traditional approach but requires LLMs to use HTTP clients, less standardized for AI interactions
- Raw MCP implementation: More boilerplate, FastMCP provides better developer experience
- gRPC: More complex, less standard for LLM tool integration
- stdio transport only: Would limit access to local processes, not network-based clients

**Transport Requirement**: The MCP server MUST use HTTP transport and be accessible over the network on port 8000. This ensures compatibility with network-based MCP clients and allows access from remote systems.

### Decision: Shared Volume for File Exchange
**What**: Use Docker volume mount (`/mnt/data/AI/n8n:/data`) shared between containers, leveraging existing n8n volume configuration. Output directory is configurable via `OUTPUT_DIRECTORY` environment variable.
**Why**:
- Simple file-based communication
- No network overhead for file transfers
- n8n can directly read files using "Read Binary File" node
- Reuses existing volume mount already configured in n8n service
- Standard Docker pattern
- Configurable output directory provides deployment flexibility

**Alternatives considered**:
- HTTP file transfer: Would require base64 encoding and larger payloads
- Database storage: Overkill for temporary media files
- New separate volume: Would require additional volume management
- Fixed output directory: Less flexible for different deployment scenarios

### Decision: MP4 Format Optimization
**What**: Configure yt-dlp to prefer MP4 format with specific format string.
**Why**:
- Maximum compatibility with downstream systems
- Standard format for web and mobile
- Efficient encoding

**Alternatives considered**:
- Best quality regardless of format: May produce incompatible formats
- WebM or other formats: Less universal compatibility

### Decision: Automatic Cleanup with Configurable Retention
**What**: Automatically remove video files older than a configurable retention period (default 7 days) based on file creation date. Retention period is configurable via `CLEANUP_RETENTION_DAYS` environment variable in docker-compose.
**Why**:
- Prevents disk space exhaustion
- Maintains recent files for active workflows
- Reduces manual maintenance overhead
- Configurable retention allows adaptation to different use cases and storage constraints
- Default 7 days provides reasonable retention for most use cases

**Alternatives considered**:
- Manual cleanup only: Requires user intervention and monitoring
- Fixed retention period: Less flexible for different deployment scenarios
- Longer retention (14-30 days): Higher disk space requirements

### Decision: Manual Cleanup MCP Tool
**What**: Provide an MCP tool to manually trigger cleanup operations in addition to automatic cleanup.
**Why**:
- Allows on-demand cleanup when needed
- Enables immediate cleanup without waiting for scheduled automatic cleanup
- Provides control over cleanup timing for specific workflows
- Complements automatic cleanup for flexible file management

**Alternatives considered**:
- Automatic cleanup only: Less flexible, requires waiting for scheduled cleanup
- Only manual cleanup: Requires constant user intervention

### Decision: Configurable Output Directory
**What**: Output directory is configurable via `OUTPUT_DIRECTORY` environment variable in docker-compose, defaulting to `/data` if not set.
**Why**:
- Allows flexibility in deployment configurations
- Enables different storage locations for different environments
- Maintains backward compatibility with default `/data` path
- Supports use cases where output needs to be in a different location

**Alternatives considered**:
- Fixed output directory: Less flexible for different deployment scenarios
- Runtime configuration only: Requires code changes for different deployments

### Decision: Configurable Filename Formats
**What**: Filename formats for videos and screenshots are configurable via environment variables using yt-dlp-style formatting syntax.
**Why**:
- Provides flexibility in file naming conventions
- Supports different organizational needs (e.g., by date, title, channel)
- Uses familiar yt-dlp formatting syntax for consistency
- Allows customization without code changes

**Environment Variables**:
- `VIDEO_FILENAME_FORMAT`: Format string for downloaded video filenames (yt-dlp style, e.g., `%(title)s.%(ext)s`)
- `SCREENSHOT_FILENAME_FORMAT`: Format string for screenshot filenames (e.g., `%(video_filename)s_%(timestamp)s.jpg`)

**Alternatives considered**:
- Fixed filename format: Less flexible, requires code changes for different naming needs
- Complex configuration files: More overhead than simple environment variables

### Decision: Progress Tracking for Long Operations
**What**: Provide progress updates for video downloads and conversions.
**Why**:
- Improves user experience for long-running operations
- Enables better workflow orchestration in n8n
- Allows cancellation of stuck operations
- Provides visibility into processing status

**Alternatives considered**:
- No progress tracking: Simpler but poor UX for long operations
- Polling-based status: Adds complexity and latency

### Decision: Cookies File Support for yt-dlp
**What**: Support optional cookies file parameter for yt-dlp to enable authenticated downloads (e.g., YouTube login).
**Why**:
- Enables access to age-restricted or private content
- Allows downloading from authenticated accounts
- Maintains user session state
- Standard yt-dlp feature, minimal implementation overhead

**Alternatives considered**:
- No authentication support: Limits access to public content only
- Built-in authentication: More complex, cookies file is standard approach

## Risks / Trade-offs

### Risk: Container Resource Limits
**Mitigation**: Monitor CPU/memory usage and set appropriate Docker resource limits if needed.

### Risk: Disk Space Exhaustion
**Mitigation**: Automatic cleanup of files older than 7 days based on file creation date. This prevents unbounded disk usage while preserving recently downloaded content.

### Risk: Network Isolation
**Mitigation**: Ensure Docker network configuration allows MCP clients to reach media-sidecar via HTTP on port 8000. The service exposes port 8000 for HTTP-based MCP protocol communication.

### Risk: MCP Client Compatibility
**Mitigation**: Verify that target LLM clients (Claude, GPT-4, etc.) support MCP protocol. FastMCP follows MCP specification for broad compatibility.

### Trade-off: No Authentication
**Current**: API is accessible only within Docker network (assumes trusted environment).
**Future**: Add authentication if service becomes externally accessible.

## Migration Plan
N/A - This is a new capability with no existing implementation to migrate.

### Decision: Comprehensive User Documentation
**What**: Provide a README.md file with complete setup, configuration, usage, and troubleshooting documentation.
**Why**:
- Enables users to quickly get started without deep technical knowledge
- Reduces support burden by providing self-service documentation
- Improves adoption and usability
- Documents all configuration options and MCP tools clearly

**Documentation Sections**:
- Quick start guide (prerequisites, installation, basic usage)
- Configuration guide (all environment variables with examples)
- MCP tool reference (parameters, examples, responses)
- MCP client setup (how to connect from Claude Desktop, etc.)
- Troubleshooting (common issues and solutions)
- Examples and use cases

**Alternatives considered**:
- Minimal documentation: Would require more support and reduce usability
- Separate documentation site: More overhead, README is standard and accessible

## Open Questions
- Should we add additional cleanup filters (e.g., by file size, file type, or custom patterns)?
- Should we support multiple output directories for different file types?

