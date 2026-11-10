#!/usr/bin/env python3

from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="infrastructure-agent",
    version="0.1.0",
    description="AI-powered IT administrator agent for autonomous infrastructure management",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "infrastructure-agent = infrastructure_agent.main:main",
        ],
    },
    python_requires=">=3.12",
)