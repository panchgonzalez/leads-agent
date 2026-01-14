#!/usr/bin/env python3
"""
Backward-compatible shim for leads-agent.

This file exists for convenience. The recommended way to run leads-agent is:

    leads-agent --help       # CLI commands
    leads-agent run          # Start the API server
    leads-agent backtest     # Test against historical messages

Or directly via Python:

    python -m leads_agent --help
"""

from leads_agent.cli import main

if __name__ == "__main__":
    main()
