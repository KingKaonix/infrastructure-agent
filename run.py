#!/usr/bin/env python3
"""Run the Infrastructure Agent"""

import asyncio
import sys
import os

# Add the agent package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from infrastructure_agent.main import main

async def main_entry():
    """Entry point for running the agent"""
    try:
        await main()
    except KeyboardInterrupt:
        print("\nShutting down agent...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main_entry())