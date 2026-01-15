#!/bin/bash

# Test script for YTDLP MCP Server
# Usage: ./test_video_metadata.sh [host:port]
# Example: ./test_video_metadata.sh localhost:8000
# Example: ./test_video_metadata.sh 192.168.1.100:8000

set -e

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
        echo "$json_input" | jq '.'
    elif [ "$JSON_FORMATTER" = "python3" ]; then
        echo "$json_input" | python3 -m json.tool 2>/dev/null || echo "$json_input"
    else
        echo "$json_input"
    fi
}

# Example video URLs to test
TEST_URLS=(
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    "https://www.youtube.com/watch?v=jNQXAC9IVRw"
)

# Function to make MCP tool call using FastMCP HTTP protocol
# FastMCP typically uses POST with JSON-RPC 2.0 format
call_mcp_tool() {
    local tool_name="$1"
    local params_json="$2"
    
    # Try common FastMCP HTTP endpoints
    # FastMCP may use different patterns - adjust based on actual implementation
    local endpoints=(
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
            break
        fi
        
        # Format 2: Simpler POST format
        response=$(curl -s -X POST "${SERVER_URL}${endpoint}" \
            -H "Content-Type: application/json" \
            -d "{
                \"tool\": \"${tool_name}\",
                \"arguments\": ${params_json}
            }" 2>/dev/null || echo "")
        
        if [ -n "$response" ] && echo "$response" | grep -qE "(status|result|error)"; then
            found=true
            break
        fi
        
        # Format 3: Direct tool call
        response=$(curl -s -X POST "${SERVER_URL}${endpoint}/${tool_name}" \
            -H "Content-Type: application/json" \
            -d "${params_json}" 2>/dev/null || echo "")
        
        if [ -n "$response" ] && echo "$response" | grep -qE "(status|result|error)"; then
            found=true
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
    response=$(call_mcp_tool "download_video" "$PARAMS_JSON" 2>&1)
    
    if echo "$response" | grep -q "error" && ! echo "$response" | grep -q "\"status\": \"success\""; then
        echo "Error calling tool:"
        format_json "$response"
        echo ""
        continue
    fi
    
    echo "Response:"
    format_json "$response"
    echo ""
    
    # Extract and display metadata summary if available
    if echo "$response" | grep -q "metadata"; then
        echo "Metadata Summary:"
        if [ "$JSON_FORMATTER" = "jq" ]; then
            echo "$response" | jq -r '.metadata // .result.metadata // {} | 
                "  Title: \(.title // "N/A")
  Duration: \(.duration // "N/A")s
  Uploader: \(.uploader // "N/A")
  View Count: \(.view_count // "N/A")
  Thumbnail: \(.thumbnail // "N/A")"' 2>/dev/null || echo "  (Could not parse metadata)"
        elif [ "$JSON_FORMATTER" = "python3" ]; then
            echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    meta = data.get('metadata') or data.get('result', {}).get('metadata', {})
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
