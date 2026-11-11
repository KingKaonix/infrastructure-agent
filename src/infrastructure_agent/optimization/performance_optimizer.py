"""Performance Optimizer for Infrastructure Agent"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

from ..core.config import get_config
from ..core.state import StateRepository
from ..deployment.ssh_executor import SSHExecutor, SSHResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OptimizationResult:
    """Result from an optimization operation"""

    def __init__(self, success: bool, message: str = "", actions_taken: List[Dict] = None):
        self.success = success
        self.message = message
        self.actions_taken = actions_taken or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "actions_taken": [
                a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions_taken
            ],
        }


class PerformanceOptimizer:
    """Monitors and optimizes performance across all devices"""

    def __init__(self, config_path: str = "config/agent_config.json", ssh_executor=None):
        self.config = get_config()
        self.ssh_executor = ssh_executor or SSHExecutor()
        self.state = StateRepository(self.config.get("state", {}).get("database", "state/agent.db"))
        self.check_interval = self.config.get("optimization", {}).get(
            "check_interval", 1800
        )  # 30 minutes
        self.cpu_threshold = self.config.get("optimization", {}).get("cpu_threshold", 80)
        self.memory_threshold = self.config.get("optimization", {}).get("memory_threshold", 85)
        self.disk_threshold = self.config.get("optimization", {}).get("disk_threshold", 80)
        self.optimization_history: List[Dict] = []
        self._stop_event = asyncio.Event()
        self.load_history()

    def load_history(self) -> None:
        """Load optimization history from SQLite."""
        self.optimization_history = self.state.list_optimization_cycles()

    def save_history(self) -> None:
        """Compatibility hook; cycles are persisted as they complete."""

    async def start_periodic_checks(self) -> None:
        """Start the periodic optimization loop"""
        logger.info(f"Starting performance optimization checks every {self.check_interval}s")

        while not self._stop_event.is_set():
            try:
                await self.run_optimization_cycle()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                logger.error(f"Error in optimization cycle: {e}")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass

    def stop(self) -> None:
        """Request a clean stop for the periodic scheduler."""
        self._stop_event.set()

    async def run_optimization_cycle(self) -> None:
        """Run one full optimization cycle across all devices"""
        logger.info("Starting optimization cycle")

        devices = self.ssh_executor.get_all_devices()
        total_devices = len(devices)
        successful_checks = 0

        for ip, device in devices.items():
            try:
                if getattr(device, "stale", False) or not device.ssh_available:
                    continue

                result = await self.optimize_device(ip)
                self.optimization_history.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "device_ip": ip,
                        "result": result.to_dict(),
                    }
                )
                self.state.record_optimization_cycle(
                    ip,
                    status="success" if result.success else "failure",
                    metrics={"actions": json.loads(result.stdout).get("actions", [])}
                    if result.stdout
                    else {},
                    recommendations=[],
                    completed_at=datetime.now().isoformat(),
                )

                if result.success:
                    successful_checks += 1

                # Save history periodically
                if len(self.optimization_history) % 10 == 0:
                    self.save_history()

            except Exception as e:
                logger.error(f"Error optimizing device {ip}: {e}")

        logger.info(
            f"Optimization cycle complete: {successful_checks}/{total_devices} devices optimized"
        )

        # Save final history
        self.save_history()

    async def optimize_device(self, device_ip: str) -> SSHResult:
        """Optimize a single device"""
        logger.info(f"Optimizing device: {device_ip}")

        actions = []

        try:
            # Check CPU usage
            cpu_result = await self.ssh_executor.execute_command(
                device_ip, "LC_ALL=C top -bn1 | awk '/Cpu\\(s\\)/ {print 100 - $8; exit}'"
            )

            if cpu_result.success:
                cpu_usage = self.parse_cpu_usage(cpu_result.stdout)
                actions.append(
                    {
                        "action": "check_cpu",
                        "cpu_usage": cpu_usage,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                if cpu_usage and cpu_usage > self.cpu_threshold:
                    # Try to find high CPU processes and suggest restart
                    top_result = await self.ssh_executor.execute_command(
                        device_ip, "ps aux --sort=-%cpu | head -n 10"
                    )

                    if top_result.success:
                        actions.append(
                            {
                                "action": "identify_high_cpu_processes",
                                "processes": top_result.stdout[:500],
                                "timestamp": datetime.now().isoformat(),
                            }
                        )

                        # Suggest restarting top process
                        # Note: We won't auto-restart without explicit user permission
                        # but we'll log the recommendation

            # Check memory usage
            memory_result = await self.ssh_executor.execute_command(
                device_ip, "free -b | awk '/Mem:/ {printf \"%s %s\\n\", $2, $3}'"
            )

            if memory_result.success:
                memory_usage = self.parse_memory_usage(memory_result.stdout)
                actions.append(
                    {
                        "action": "check_memory",
                        "memory_usage": memory_usage,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                if memory_usage and memory_usage > self.memory_threshold:
                    # Suggest restarting services or clearing cache
                    actions.append(
                        {
                            "action": "high_memory_warning",
                            "message": "Memory usage above threshold",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            # Check disk usage
            disk_result = await self.ssh_executor.execute_command(
                device_ip, "df -P -k / | awk 'NR==2 {gsub(/%/,\"\",$5); print $5}'"
            )

            if disk_result.success:
                disk_usage = self.parse_disk_usage(disk_result.stdout)
                actions.append(
                    {
                        "action": "check_disk",
                        "disk_usage": disk_usage,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                if disk_usage and disk_usage > self.disk_threshold:
                    actions.append(
                        {
                            "action": "cleanup_recommendation",
                            "message": "Disk usage above threshold; cleanup requires explicit approval",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            # Return structured result
            return SSHResult(
                success=True, stdout=json.dumps({"actions": actions, "device_ip": device_ip})
            )

        except Exception as e:
            logger.error(f"Error optimizing device {device_ip}: {e}")
            return SSHResult(success=False, stderr=str(e))

    @staticmethod
    def parse_cpu_usage(output: str) -> Optional[float]:
        """Parse CPU usage from top output"""
        try:
            value = float(output.strip().splitlines()[0])
            return max(0.0, min(100.0, value))
        except Exception:
            pass
        return None

    @staticmethod
    def parse_memory_usage(output: str) -> Optional[float]:
        """Parse memory usage from free output"""
        try:
            parts = output.split()
            if len(parts) >= 2:
                total = float(parts[0])
                used = float(parts[1])
                if total > 0:
                    return (used / total) * 100
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def parse_disk_usage(output: str) -> Optional[float]:
        """Parse disk usage from df output"""
        try:
            value = output.strip().splitlines()[0]
            return float(value.rstrip("%"))
        except (ValueError, IndexError):
            pass
        return None
