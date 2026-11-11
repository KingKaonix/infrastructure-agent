"""Network discovery for Infrastructure Agent"""

import asyncio
import logging
import ipaddress
import json
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime

from ..core.config import get_config
from ..core.state import StateRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeviceInfo:
    """Information about a discovered device"""

    def __init__(self, ip: str, hostname: str = "", os: str = "", open_ports: List[int] = None):
        self.ip = ip
        self.hostname = hostname
        self.os = os
        self.open_ports = open_ports or []
        self.last_seen = datetime.now()
        self.ssh_available = False
        self.stale = False
        self.ssh_username = ""
        self.ssh_password = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "hostname": self.hostname,
            "os": self.os,
            "open_ports": self.open_ports,
            "last_seen": self.last_seen.isoformat(),
            "ssh_available": self.ssh_available,
            "ssh_username": self.ssh_username,
            "stale": self.stale,
        }


class NetworkDiscovery:
    """Discovers devices on the network"""

    def __init__(
        self,
        *,
        inventory_path: str | Path | None = None,
        state_repository: StateRepository | None = None,
        concurrency: int = 32,
    ):
        self.config = get_config()
        self.devices: Dict[str, DeviceInfo] = {}
        state_path = self.config.get("state", {}).get("database", "state/agent.db")
        self.state = state_repository or StateRepository(state_path)
        self.discovery_file = (
            Path(inventory_path).expanduser().resolve() if inventory_path else None
        )
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(concurrency)
        self.load_inventory()

    def load_inventory(self) -> None:
        """Load device inventory from file"""
        for data in self.state.list_devices():
            device = DeviceInfo(
                ip=data["ip"],
                hostname=data.get("hostname", ""),
                os=data.get("os", ""),
                open_ports=json.loads(data.get("open_ports", "[]")),
            )
            device.ssh_available = bool(data.get("ssh_available", False))
            device.stale = bool(data.get("stale", False))
            self.devices[device.ip] = device

    def save_inventory(self) -> None:
        """Save device inventory to file"""
        for device in self.devices.values():
            self.state.upsert_device(
                device.ip,
                hostname=device.hostname,
                os=device.os,
                open_ports=device.open_ports,
                ssh_available=device.ssh_available,
                discovered_at=device.last_seen.isoformat(),
                stale=getattr(device, "stale", False),
            )

    async def start_discovery(self) -> None:
        """Start periodic network discovery"""
        logger.info("Starting network discovery")

        while not self._stop_event.is_set():
            try:
                await self.discover_network()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.config.get("network", {}).get("discovery_interval", 300),
                    )
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                logger.error(f"Error during discovery: {e}")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass

    async def discover_network(self) -> None:
        """Discover devices on the network"""
        network_config = self.config.get("network", {})
        scan_range = network_config.get("scan_range", "")
        auto_detect = network_config.get("auto_detect", True)
        scan_private_only = network_config.get("scan_private_only", False)
        allowed_subnets = network_config.get(
            "allowed_subnets", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
        )

        logger.info(f"Scanning network range: {scan_range}")
        logger.info(f"Scanning private only: {scan_private_only}")
        self.state.mark_devices_stale()
        for device in self.devices.values():
            device.stale = True

        # Determine which networks to scan. Auto-detection prevents a copied
        # config from silently scanning a different LAN than the host uses.
        networks_to_scan: list[ipaddress.IPv4Network] = []
        if auto_detect:
            networks_to_scan = await self._detect_local_networks()
        if not networks_to_scan:
            try:
                if scan_private_only:
                    # Scan only explicitly configured private subnets.
                    for subnet in allowed_subnets:
                        networks_to_scan.append(ipaddress.IPv4Network(subnet))
                else:
                    # Scan the full configured range
                    networks_to_scan.append(ipaddress.IPv4Network(scan_range))
            except Exception as e:
                logger.error(f"Invalid network configuration: {e}")

        if not networks_to_scan:
            if not scan_range:
                logger.warning(
                    "No discovery range configured; refusing an unbounded private-network scan"
                )
                return
            networks_to_scan = [ipaddress.IPv4Network(scan_range, strict=False)]

        for network in networks_to_scan:
            await self._scan_network_range(network)

    async def _detect_local_networks(self) -> list[ipaddress.IPv4Network]:
        try:
            process = await asyncio.create_subprocess_exec(
                "ip",
                "-o",
                "-4",
                "addr",
                "show",
                "scope",
                "global",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=3)
            networks = []
            for line in stdout.decode().splitlines():
                fields = line.split()
                if "inet" not in fields:
                    continue
                cidr = fields[fields.index("inet") + 1]
                network = ipaddress.ip_network(cidr, strict=False)
                if isinstance(network, ipaddress.IPv4Network) and network.prefixlen >= 16:
                    networks.append(network)
            return list(dict.fromkeys(networks))
        except (asyncio.TimeoutError, OSError, ValueError, IndexError):
            return []

    async def _scan_network_range(self, network: ipaddress.IPv4Network) -> None:
        """Scan a single network range for devices"""
        logger.info(f"Scanning network: {network}")

        try:
            # Get live hosts (ARP ping)
            hosts = network.hosts()
            host_list = list(hosts)

            await asyncio.gather(*(self._bounded_scan(str(host)) for host in host_list))
            self.save_inventory()

        except Exception as e:
            logger.error(f"Error scanning network {network}: {e}")

    async def _bounded_scan(self, ip: str) -> None:
        async with self._semaphore:
            try:
                await asyncio.wait_for(self.scan_device(ip), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("Discovery timed out for %s", ip)

    async def scan_device(self, ip: str) -> None:
        """Scan a single device"""
        logger.info(f"Scanning device: {ip}")

        try:
            # Scan ports
            open_ports = await self.scan_ports(ip)
            ssh_available = 22 in open_ports or await self.check_ssh(ip)

            if not open_ports and not ssh_available:
                return

            # Only perform slower reverse DNS and OS detection for responsive hosts.
            hostname = await self.get_hostname(ip)
            os_info = await self.detect_os(ip)

            device = DeviceInfo(ip=ip, hostname=hostname, os=os_info, open_ports=open_ports)
            device.ssh_available = ssh_available
            device.stale = False

            self.devices[ip] = device
            logger.info(
                f"Discovered device: {ip} (hostname: {hostname}, OS: {os_info}, open_ports: {open_ports}, SSH: {ssh_available}"
            )

        except Exception as e:
            logger.error(f"Error scanning device {ip}: {e}")

    async def get_hostname(self, ip: str) -> str:
        """Get hostname for an IP address"""
        try:
            result = await asyncio.create_subprocess_exec(
                "host", ip, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            hostname = stdout.decode().strip()
            return "" if "not found" in hostname.lower() else hostname
        except Exception as e:
            logger.debug(f"Could not resolve hostname for {ip}: {e}")
            return ""

    async def scan_ports(self, ip: str, port_range: str = "1-1000") -> List[int]:
        """Scan ports on a device"""
        try:
            result = await asyncio.create_subprocess_exec(
                "nmap",
                "-p",
                port_range,
                "-oG",
                "-",
                ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()

            ports = []
            for line in stdout.decode().split("\n"):
                if "open" in line:
                    try:
                        port = int(line.split("/")[0].strip())
                        ports.append(port)
                    except ValueError:
                        pass
            if ports:
                return ports
            # Minimal fallback when nmap is not installed.
            common_ports = (22, 80, 443, 3000, 8000, 8080)
            checks = await asyncio.gather(
                *(self._probe_port(ip, port) for port in common_ports), return_exceptions=True
            )
            return [port for port, open_ in zip(common_ports, checks) if open_ is True]

        except Exception as e:
            logger.debug(f"Could not scan ports for {ip}: {e}")
            return []

    async def detect_os(self, ip: str) -> str:
        """Detect OS of a device"""
        try:
            result = await asyncio.create_subprocess_exec(
                "nmap",
                "-O",
                "-oG",
                "-",
                ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()

            for line in stdout.decode().split("\n"):
                if "OS details:" in line:
                    os_info = line.split("OS details:")[1].split(",")[0].strip()
                    return os_info

        except Exception as e:
            logger.debug(f"Could not detect OS for {ip}: {e}")

        return ""

    async def check_ssh(self, ip: str) -> bool:
        """Check if SSH is available on a device"""
        try:
            result = await asyncio.create_subprocess_exec(
                "nc",
                "-z",
                "-w",
                "2",
                ip,
                "22",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await result.communicate()
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Could not check SSH for {ip}: {e}")
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 22), timeout=2)
                writer.close()
                await writer.wait_closed()
                return True
            except (OSError, asyncio.TimeoutError):
                return False

    async def _probe_port(self, ip: str, port: int) -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1)
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    def get_device_by_ip(self, ip: str) -> DeviceInfo | None:
        """Get device info by IP"""
        return self.devices.get(ip)

    def get_all_devices(self) -> Dict[str, DeviceInfo]:
        """Get all discovered devices"""
        return self.devices

    def stop_discovery(self) -> asyncio.Task:
        """Stop discovery (placeholder - would need proper cleanup)"""

        async def stop():
            logger.info("Stopping discovery")
            self._stop_event.set()
            # Save final inventory
            self.save_inventory()

        return asyncio.create_task(stop())
