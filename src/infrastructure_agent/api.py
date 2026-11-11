"""Small FastAPI adapter over the core services.

The API is intentionally thin: policy, auditing, deployment, and SSH behavior
remain in the same services used by the CLI.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class SSHRequest(BaseModel):
    target: str
    command: str = Field(min_length=1)
    approved: bool = False


class DeployRequest(BaseModel):
    repository: str
    target: str


def create_app(*, discovery=None, ssh=None, deployer=None) -> FastAPI:
    """Create an API instance with injected services for production or tests."""
    if discovery is None:
        from .discovery.network_discovery import NetworkDiscovery

        discovery = NetworkDiscovery()
    if ssh is None:
        from .deployment.ssh_executor import SSHExecutor

        ssh = SSHExecutor(device_registry=discovery)
    if deployer is None:
        from .deployment.deployer import Deployer

        deployer = Deployer(ssh_executor=ssh)

    app = FastAPI(title="Infrastructure Agent", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        devices = discovery.get_all_devices()
        return {"devices": [device.to_dict() for device in devices.values()], "count": len(devices)}

    @app.post("/ssh")
    async def execute_ssh(request: SSHRequest) -> dict[str, Any]:
        result = await ssh.execute_command(
            request.target, request.command, approved=request.approved
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.to_dict())
        return result.to_dict()

    @app.post("/deploy")
    async def deploy(request: DeployRequest) -> dict[str, Any]:
        result = await deployer.deploy_from_github(request.repository, request.target)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.to_dict())
        return result.to_dict()

    return app
