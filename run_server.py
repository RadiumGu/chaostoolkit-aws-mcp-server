#!/usr/bin/env python3
"""
Quick start script for Chaos Toolkit AWS MCP Server

This script can be used to test the server locally or run it directly.
"""

import sys
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent / "src"))

from chaostoolkit_aws_mcp_server.server import main

if __name__ == "__main__":
    main()
