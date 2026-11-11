#!/usr/bin/env python3
"""Run the Infrastructure Agent"""

import sys
import os

# Add the agent package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from infrastructure_agent.main import main

if __name__ == "__main__":
    sys.exit(main())
