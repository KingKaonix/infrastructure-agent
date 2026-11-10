"""SSH Executor for Infrastructure Agent"""

import asyncio
import logging
import json
import os
from typing import Dict, List, Any, Optional
from pathlib import Path
import asyncssh

from ..core.config import get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SSHResult:
    """Result from an SSH command execution"""

    def __init__(self, success: bool, stdout: str = "", stderr: str = "",
                 exit_code: int = -1, execution_time: float = 0.0):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.execution_time = execution_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "execution_time": self.execution_time
        }


class SSHExecutor:
    """Executes commands via SSH on remote devices"""

    def __init__(self):
        self.config = get_config()
        self.active_connections: Dict[str, asyncssh.connect] = {}
        self.session_timeout = self.config.get("ssh", {}).get("timeout", 30)

    async def connect(self, device_ip: str, username: str = None, key_path: str = None) -> bool:
        """Establish SSH connection to a device"""
        ip = device_ip
        user = username or self.config.get("ssh", {}).get("username", "")
        key = key_path or self.config.get("ssh", {}).get("key_path", "")

        # Expand ~
        if key and key.startswith("~"):
            key = os.path.expanduser(key)

        try:
            connect_kwargs = dict(
                host=ip,
                username=user,
                client_keys=[key] if key else None,
                known_hosts=None,
                timeout=self.session_timeout,
            )

            # Remove None values
            connect_kwargs = {k: v for k, v in connect_kwargs.items() if v is not None}

            logger.info(f"Connecting to SSH: {ip} as {user}")
            self.active_connections[ip] = await asyncssh.connect(**connect_kwargs)
            logger.info(f"SSH connection established: {ip}")
            return True

        except Exception as e:
            logger.error(f"SSH connection failed to {ip}: {e}")
            # Clean up failed connection
            if ip in self.active_connections:
                del self.active_connections[ip]
            return False

    async def execute_command(self, device_ip: str, command: str,
                              username: str = None, password: str = None,
                              timeout: int = None) -> SSHResult:
        """Execute a command via SSH"""
        timeout = timeout or self.config.get("ssh", {}).get("timeout", 30)

        try:
            connect = self.active_connections.get(device_ip)
            if connect is None:
                # Try to connect
                await self.connect(device_ip, username)

            connect = self.active_connections.get(device_ip)
            if connect is None:
                return SSHResult(success=False, stderr=f"Could not establish SSH connection to {device_ip}")

            logger.info(f"Executing command on {device_ip}: {command}")

            # Execute the command
            result = await connect.run_command(
                command,
                timeout=timeout,
                encoding='utf-8'
            )

            execution_time = result.duration if hasattr(result, 'duration') else 0.0

            return SSHResult(
                success=result.exit_status == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status or -1,
                execution_time=execution_time
            )

        except asyncio.TimeoutError:
            logger.error(f"SSH command timed out on {device_ip}: {command}")
            return SSHResult(success=False, stderr=f"Command timed out after {timeout}s")

        except Exception as e:
            logger.error(f"SSH command execution error on {device_ip}: {e}")
            return SSHResult(success=False, stderr=str(e))

    async def execute_script(self, device_ip: str, script_path: str,
                             username: str = None) -> SSHResult:
        """Execute a script via SSH"""
        try:
            connect = self.active_connections.get(device_ip)
            if connect is None:
                await self.connect(device_ip, username)

            connect = self.active_connections.get(device_ip)
            if connect is None:
                return SSHResult(success=False, stderr=f"Could not establish SSH connection to {device_ip}")

            # Read script and execute
            async with connect.start_session() as session:
                result = await session.run(
                    f"bash {script_path}",
                    encoding='utf-8'
                )

            return SSHResult(
                success=result.exit_status == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status or -1
            )

        except Exception as e:
            logger.error(f"SSH script execution error on {device_ip}: {e}")
            return SSHResult(success=False, stderr=str(e))

    async def close_connection(self, device_ip: str) -> None:
        """Close SSH connection to a device"""
        if device_ip in self.active_connections:
            connect = self.active_connections[device_ip]
            connect.close()
            del self.active_connections[device_ip]
            logger.info(f"SSH connection closed: {device_ip}")

    def get_all_devices(self) -> Dict[str, Any]:
        """Get all discovered devices (placeholder - would need device registry)"""
        return {}

    async def close_all_connections(self) -> None:
        """Close all SSH connections"""
        for ip in list(self.active_connections.keys()):
            await self.close_connection(ip)