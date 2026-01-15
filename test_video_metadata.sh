#!/bin/bash

# Test script for YTDLP MCP Server
# Usage: ./test_video_metadata.sh [host:port]
# Example: ./test_video_metadata.sh localhost:8000
# Example: ./test_video_metadata.sh 192.168.1.100:8000

set -u

# Get host:port from argument or default to localhost:8000
HOST_PORT="${1:-localhost:8000}"

# Validate host:port format
if [[ ! "$HOST_PORT" =~ ^[a-zA-Z0-9._-]+:[0-9]+$ ]]; then
    echo "Error: Invalid host:port format. Expected format: host:port" >&2
    echo "Example: localhost:8000 or 192.168.1.100:8000" >&2
    exit 1
fi

SERVER_URL="http://${HOST_PORT}"

echo "Testing YTDLP MCP Server at ${SERVER_URL}"
echo "=========================================="
echo ""

# Check if server is reachable
if ! curl -s --connect-timeout 5 "${SERVER_URL}" > /dev/null 2>&1; then
    echo "Error: Cannot connect to MCP server at ${SERVER_URL}" >&2
    echo "Make sure the server is running: docker-compose up" >&2
    exit 1
fi

echo "✓ Server is reachable"
echo ""

# Initialize MCP session (FastMCP may require a session ID header)
MCP_SESSION_ID=""
INIT_ENDPOINT="/mcp"
INIT_PAYLOAD='{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": { "name": "ytdlp-mcp-test", "version": "1.0" },
    "capabilities": {}
  }
}'

INIT_TMP_HEADERS=$(mktemp)
INIT_TMP_BODY=$(mktemp)

curl -s -D "$INIT_TMP_HEADERS" -o "$INIT_TMP_BODY" -X POST "${SERVER_URL}${INIT_ENDPOINT}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$INIT_PAYLOAD" >/dev/null 2>&1

MCP_SESSION_ID=$(grep -i '^mcp-session-id:' "$INIT_TMP_HEADERS" | head -n 1 | sed 's/^[^:]*:[[:space:]]*//;s/[[:space:]]*$//')

if [ -z "$MCP_SESSION_ID" ]; then
    # Some servers may return the session id in the body
    MCP_SESSION_ID=$(grep -oE '"sessionId"[[:space:]]*:[[:space:]]*"[^"]+"' "$INIT_TMP_BODY" | head -n 1 | sed 's/.*"sessionId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
fi

rm -f "$INIT_TMP_HEADERS" "$INIT_TMP_BODY"

SESSION_HEADER=()
if [ -n "$MCP_SESSION_ID" ]; then
    echo "✓ MCP session initialized (ID: ${MCP_SESSION_ID})"
    echo ""
    SESSION_HEADER=(-H "MCP-Session-Id: ${MCP_SESSION_ID}")
else
    echo "Warning: MCP session ID not found. Init response:" >&2
    cat "$INIT_TMP_BODY" >&2
    echo "" >&2
    echo ""
fi

# Check if jq is available for JSON formatting, otherwise use Python
if command -v jq &> /dev/null; then
    JSON_FORMATTER="jq"
elif command -v python3 &> /dev/null; then
    JSON_FORMATTER="python3"
else
    echo "Warning: Neither jq nor python3 found. JSON output will not be formatted." >&2
    JSON_FORMATTER="cat"
fi

# Function to format JSON
format_json() {
    local json_input="$1"
    if [ "$JSON_FORMATTER" = "jq" ]; then
        if echo "$json_input" | jq -e . >/dev/null 2>&1; then
            echo "$json_input" | jq '.'
        else
            echo "$json_input"
        fi
    elif [ "$JSON_FORMATTER" = "python3" ]; then
        echo "$json_input" | python3 -m json.tool 2>/dev/null || echo "$json_input"
    else
        echo "$json_input"
    fi
}

# Read example URLs from file if it exists, otherwise use defaults
EXAMPLE_URLS_FILE="example_urls.txt"
if [ -f "$EXAMPLE_URLS_FILE" ]; then
    # Read URLs from file, skipping empty lines and comments
    # Use portable method that works in both bash and zsh
    TEST_URLS=()
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        line_trimmed=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if [ -n "$line_trimmed" ] && [ "${line_trimmed#\#}" = "$line_trimmed" ]; then
            TEST_URLS+=("$line_trimmed")
        fi
    done < "$EXAMPLE_URLS_FILE"
    echo "Loaded ${#TEST_URLS[@]} URLs from $EXAMPLE_URLS_FILE"
    echo ""
else
    # Fallback to default URLs if file doesn't exist
    echo "Warning: $EXAMPLE_URLS_FILE not found. Using default test URLs." >&2
    TEST_URLS=(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    )
fi

# Function to make MCP tool call using FastMCP HTTP protocol
# FastMCP typically uses POST with JSON-RPC 2.0 format
call_mcp_tool() {
    local tool_name="$1"
    local params_json="$2"
    
    # Try common FastMCP HTTP endpoints
    # FastMCP may use different patterns - adjust based on actual implementation
    local endpoints=(
        "/mcp"
        "/mcp/tools/call"
        "/tools/call"
        "/api/tools/call"
        "/call"
    )
    
    local response=""
    local found=false
    
    # Try JSON-RPC 2.0 format (standard for MCP over HTTP)
    for endpoint in "${endpoints[@]}"; do
        # Format 1: Standard JSON-RPC 2.0
        response=$(curl -s -X POST "${SERVER_URL}${endpoint}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            "${SESSION_HEADER[@]}" \
            -d "{
                \"jsonrpc\": \"2.0\",
                \"id\": 1,
                \"method\": \"tools/call\",
                \"params\": {
                    \"name\": \"${tool_name}\",
                    \"arguments\": ${params_json}
                }
            }" 2>/dev/null || echo "")
        
        if [ -n "$response" ] && echo "$response" | grep -qE "(status|result|error)"; then
            found=true
            MCP_ENDPOINT_USED="${endpoint}"
            MCP_ENDPOINT_USED_MODE="jsonrpc"
            break
        fi
        
        # Format 2: Simpler POST format
        response=$(curl -s -X POST "${SERVER_URL}${endpoint}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            "${SESSION_HEADER[@]}" \
            -d "{
                \"tool\": \"${tool_name}\",
                \"arguments\": ${params_json}
            }" 2>/dev/null || echo "")
        
        if [ -n "$response" ] && echo "$response" | grep -qE "(status|result|error)"; then
            found=true
            MCP_ENDPOINT_USED="${endpoint}"
            MCP_ENDPOINT_USED_MODE="simple"
            break
        fi
        
        # Format 3: Direct tool call
        response=$(curl -s -X POST "${SERVER_URL}${endpoint}/${tool_name}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            "${SESSION_HEADER[@]}" \
            -d "${params_json}" 2>/dev/null || echo "")
        
        if [ -n "$response" ] && echo "$response" | grep -qE "(status|result|error)"; then
            found=true
            MCP_ENDPOINT_USED="${endpoint}/${tool_name}"
            MCP_ENDPOINT_USED_MODE="direct"
            break
        fi
    done
    
    if [ "$found" = false ] || [ -z "$response" ]; then
        echo "{\"error\": \"Could not determine MCP endpoint format. Tried endpoints: ${endpoints[*]}\", \"note\": \"Check FastMCP documentation for correct endpoint format\"}"
        return 1
    fi
    
    echo "$response"
}

# Test each URL
for url in "${TEST_URLS[@]}"; do
    echo "Testing URL: ${url}"
    echo "----------------------------------------"
    
    # Prepare parameters as JSON
    PARAMS_JSON=$(cat <<EOF
{
  "url": "${url}"
}
EOF
)
    
    # Make tool call
    response=$(call_mcp_tool "download_video" "$PARAMS_JSON")
    call_status=$?

    if [ $call_status -ne 0 ]; then
        echo "Error calling tool (non-zero exit status):"
        format_json "$response"
        echo ""
        continue
    fi

    if [ -n "${MCP_ENDPOINT_USED:-}" ] && [ "${MCP_ENDPOINT_USED:-}" != "${LAST_ENDPOINT_USED:-}" ]; then
        echo "Using endpoint: ${MCP_ENDPOINT_USED} (${MCP_ENDPOINT_USED_MODE})"
        LAST_ENDPOINT_USED="${MCP_ENDPOINT_USED}"
    fi
    
    # Handle SSE responses (extract the last JSON "data:" line if present)
    response_json=$(echo "$response" | sed -n 's/^data: //p' | tail -n 1)
    if [ -z "$response_json" ]; then
        response_json="$response"
    fi

    if echo "$response_json" | grep -q "error" && ! echo "$response_json" | grep -q "\"status\": \"success\""; then
        echo "Error calling tool:"
        format_json "$response_json"
        echo ""
        continue
    fi
    
    echo "Response:"
    format_json "$response_json"
    echo ""
    
    # Extract and display metadata summary if available
    if echo "$response_json" | grep -q "metadata"; then
        echo "Metadata Summary:"
        if [ "$JSON_FORMATTER" = "jq" ]; then
            echo "$response_json" | jq -r '
                .metadata
                // .result.metadata
                // .result.structuredContent.metadata
                // (try (.result.content[0].text | fromjson | .metadata) catch {})
                // {} |
                "  Title: \(.title // "N/A")\n  Duration: \(.duration // "N/A")s\n  Uploader: \(.uploader // "N/A")\n  View Count: \(.view_count // "N/A")\n  Thumbnail: \(.thumbnail // "N/A")"
            ' 2>/dev/null || echo "  (Could not parse metadata)"
        elif [ "$JSON_FORMATTER" = "python3" ]; then
            echo "$response_json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    meta = data.get('metadata') or data.get('result', {}).get('metadata') or data.get('result', {}).get('structuredContent', {}).get('metadata')
    if not meta:
        content = data.get('result', {}).get('content', [])
        if content and isinstance(content, list):
            try:
                meta = json.loads(content[0].get('text', '{}')).get('metadata', {})
            except Exception:
                meta = {}
    print(f\"  Title: {meta.get('title', 'N/A')}\")
    print(f\"  Duration: {meta.get('duration', 'N/A')}s\")
    print(f\"  Uploader: {meta.get('uploader', 'N/A')}\")
    print(f\"  View Count: {meta.get('view_count', 'N/A')}\")
    print(f\"  Thumbnail: {meta.get('thumbnail', 'N/A')}\")
except:
    print('  (Could not parse metadata)')
" 2>/dev/null || echo "  (Could not parse metadata)"
        else
            echo "  (Install jq or python3 to view formatted metadata summary)"
        fi
    fi
    
    echo ""
    echo "========================================"
    echo ""
done

echo "Test completed!"
echo ""
echo "Note: If tool calls failed, check:"
echo "  1. FastMCP HTTP endpoint format (may differ from examples)"
echo "  2. Server logs: docker-compose logs ytdlp-mcp"
echo "  3. FastMCP documentation for correct endpoint URLs"
