#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
source /Users/4jp/Workspace/ops-witness/scripts/.github-mcp.env
exec npx -y @modelcontextprotocol/server-github
