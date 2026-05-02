#!/usr/bin/env python3
"""
Observable Agent Control Panel - Token-Optimized, Self-Learning DevOps Control Plane

Entry point that delegates to either CLI or MCP server mode.

Usage:
    python main.py --mode cli       (interactive terminal)
    python main.py --mode server    (MCP stdio server for IDEs)
"""

import argparse
import sys
import os

def load_env() -> None:
    """Simple .env loader to avoid external dependencies."""
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Observable Agent Control Panel")
    parser.add_argument(
        "--mode",
        choices=["cli", "server"],
        default="cli",
        help="Run mode: cli (terminal) or server (MCP stdio)",
    )
    args = parser.parse_args()

    if args.mode == "cli":
        from devops_agent.cli import main as cli_main
        cli_main()
    elif args.mode == "server":
        from observable_agent_panel.server import main as server_main
        server_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
