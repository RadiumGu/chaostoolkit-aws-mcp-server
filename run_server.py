#!/usr/bin/env python3
"""Run the MCP server from a source checkout without installing it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from chaostoolkit_aws_mcp_server.server import main

if __name__ == "__main__":
    main()
