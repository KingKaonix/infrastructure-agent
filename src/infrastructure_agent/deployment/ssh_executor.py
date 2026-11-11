"""SSH Executor for Infrastructure Agent"""

import asyncio
import logging
import os
from typing import Any, Dict

try:
    import asyncssh
except ImportError:  # Keep read-only CLI/help and unit tests usable before extras install.
    asyncssh: Any = None

from ..core.config import get_config
from ..core.audit import AuditLog
from ..core.policy import CommandPolicy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SSHResult:
    """Result from an SSH command execution"""

    def __init__(
        self,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = -1,
        execution_time: float = 0.0,
    ):
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
            "execution_time": self.execution_time,
        }


class SSHExecutor:
    """Executes commands via SSH on remote devices"""

    def __init__(self, *, audit_log=None, policy=None, device_registry=None, ssh_client=None):
        self.config = get_config()
        self.active_connections: Dict[str, Any] = {}
        self.session_timeout = self.config.get("ssh", {}).get("timeout", 30)
        self.max_retries = int(self.config.get("ssh", {}).get("max_retries", 3))
        self.audit = audit_log or AuditLog(
            self.config.get("state", {}).get("database", "state/agent.db")
        )
        allowed = tuple(self.config.get("ssh", {}).get("allowed_hosts", ()))
        self.policy = policy or CommandPolicy(allowed_hosts=allowed)
        self.device_registry = device_registry
        self.ssh_client = ssh_client if ssh_client is not None else asyncssh

    async def connect(
        self, device_ip: str, username: str = None, key_path: str = None, password: str = None
    ) -> bool:
        """Establish SSH connection to a device"""
        if self.ssh_client is None:
            logger.error("asyncssh is not installed")
            return False
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
                known_hosts=os.path.expanduser(
                    self.config.get("ssh", {}).get("known_hosts", "~/.ssh/known_hosts")
                ),
                timeout=self.session_timeout,
            )
            if password:
                connect_kwargs["password"] = password

            # Remove None values
            connect_kwargs = {k: v for k, v in connect_kwargs.items() if v is not None}

            logger.info(f"Connecting to SSH: {ip} as {user}")
            for attempt in range(self.max_retries):
                try:
                    self.active_connections[ip] = await self.ssh_client.connect(**connect_kwargs)
                    self.audit.record("ssh.connect", target=ip, outcome="success")
                    return True
                except Exception:
                    if attempt + 1 == self.max_retries:
                        raise
                    await asyncio.sleep(
                        float(self.config.get("ssh", {}).get("retry_backoff", 0.5)) * (attempt + 1)
                    )
            logger.info(f"SSH connection established: {ip}")
            return False

        except Exception as e:
            self.audit.record(
                "ssh.connect", target=ip, outcome="failure", details={"error": str(e)}
            )
            logger.error(f"SSH connection failed to {ip}: {e}")
            # Clean up failed connection
            if ip in self.active_connections:
                del self.active_connections[ip]
            return False

    async def execute_command(
        self,
        device_ip: str,
        command: str,
        username: str = None,
        password: str = None,
        timeout: int = None,
        approved: bool = False,
    ) -> SSHResult:
        """Execute a command via SSH"""
        timeout = timeout or self.config.get("ssh", {}).get("timeout", 30)
        try:
            self.policy.check(device_ip, command, approved=approved)
        except PermissionError as exc:
            self.audit.record(
                "ssh.command", target=device_ip, outcome="denied", details={"command": command}
            )
            return SSHResult(success=False, stderr=str(exc))
        audit_id = self.audit.record("ssh.command", target=device_ip, details={"command": command})

        try:
            connect = self.active_connections.get(device_ip)
            if connect is None:
                # Try to connect
                await self.connect(device_ip, username, password=password)

            connect = self.active_connections.get(device_ip)
            if connect is None:
                return SSHResult(
                    success=False, stderr=f"Could not establish SSH connection to {device_ip}"
                )

            logger.info(f"Executing command on {device_ip}: {command}")

            # Execute the command
            result = await connect.run_command(command, timeout=timeout, encoding="utf-8")

            execution_time = result.duration if hasattr(result, "duration") else 0.0

            result = SSHResult(
                success=result.exit_status == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status if result.exit_status is not None else -1,
                execution_time=execution_time,
            )
            self.audit.record(
                "ssh.command",
                target=device_ip,
                outcome="success" if result.success else "failure",
                details={"audit_id": audit_id, "exit_code": result.exit_code},
            )
            return result

        except asyncio.TimeoutError:
            logger.error(f"SSH command timed out on {device_ip}: {command}")
            self.audit.record(
                "ssh.command", target=device_ip, outcome="timeout", details={"audit_id": audit_id}
            )
            return SSHResult(success=False, stderr=f"Command timed out after {timeout}s")

        except Exception as e:
            logger.error(f"SSH command execution error on {device_ip}: {e}")
            self.audit.record(
                "ssh.command",
                target=device_ip,
                outcome="failure",
                details={"audit_id": audit_id, "error": str(e)},
            )
            return SSHResult(success=False, stderr=str(e))

    async def execute_script(
        self, device_ip: str, script_path: str, username: str = None
    ) -> SSHResult:
        """Execute a script via SSH"""
        try:
            connect = self.active_connections.get(device_ip)
            if connect is None:
                await self.connect(device_ip, username)

            connect = self.active_connections.get(device_ip)
            if connect is None:
                return SSHResult(
                    success=False, stderr=f"Could not establish SSH connection to {device_ip}"
                )

            # Read script and execute
            async with connect.start_session() as session:
                result = await session.run(f"bash {script_path}", encoding="utf-8")

            return SSHResult(
                success=result.exit_status == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status if result.exit_status is not None else -1,
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
        if self.device_registry is not None:
            return self.device_registry.get_all_devices()
        return {}

    async def close_all_connections(self) -> None:
        """Close all SSH connections"""
        for ip in list(self.active_connections.keys()):
            await self.close_connection(ip)
