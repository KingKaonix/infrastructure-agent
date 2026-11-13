import ipaddress
import types

import pytest

from infrastructure_agent.discovery.network_discovery import (
    NetworkDiscovery,
    _is_scannable_interface,
)


@pytest.mark.parametrize("ifname", ["enp2s0", "wlan0", "br0", "eth0"])
def test_physical_interfaces_are_scannable(ifname):
    assert _is_scannable_interface(ifname)


@pytest.mark.parametrize(
    "ifname", ["lo", "docker0", "br-9a1f", "veth4c2", "virbr0", "tun0", "podman0", "wg0"]
)
def test_virtual_interfaces_are_skipped(ifname):
    assert not _is_scannable_interface(ifname)


def _discovery(**network):
    discovery = object.__new__(NetworkDiscovery)
    discovery.config = {"network": network}
    discovery.devices = {}
    discovery.state = types.SimpleNamespace(mark_devices_stale=lambda: None)
    return discovery


async def _scan_with(monkeypatch, discovery, detected):
    async def detect():
        return detected

    scanned = []

    async def record(network):
        scanned.append(str(network))

    monkeypatch.setattr(discovery, "_detect_local_networks", detect)
    monkeypatch.setattr(discovery, "_scan_network_range", record)
    await discovery.discover_network()
    return scanned


@pytest.mark.asyncio
async def test_explicit_scan_range_wins_over_auto_detection(monkeypatch):
    discovery = _discovery(scan_range="192.168.12.0/24", auto_detect=True)
    detected = [ipaddress.ip_network("172.17.0.0/16")]
    assert await _scan_with(monkeypatch, discovery, detected) == ["192.168.12.0/24"]


@pytest.mark.asyncio
async def test_auto_detection_used_without_scan_range(monkeypatch):
    discovery = _discovery(auto_detect=True)
    detected = [ipaddress.ip_network("192.168.12.0/24")]
    assert await _scan_with(monkeypatch, discovery, detected) == ["192.168.12.0/24"]


@pytest.mark.asyncio
async def test_missing_range_without_auto_detection_scans_nothing(monkeypatch):
    discovery = _discovery(auto_detect=False)
    assert await _scan_with(monkeypatch, discovery, []) == []


@pytest.mark.asyncio
async def test_invalid_scan_range_scans_nothing(monkeypatch):
    discovery = _discovery(scan_range="not-a-network", auto_detect=True)
    detected = [ipaddress.ip_network("192.168.12.0/24")]
    assert await _scan_with(monkeypatch, discovery, detected) == []
