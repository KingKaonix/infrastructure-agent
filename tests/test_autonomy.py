import pytest

from infrastructure_agent.autonomy import AutonomousSupervisor


class FakeDiscovery:
    def get_all_devices(self):
        return {}

    async def discover_network(self):
        return None


class FakeOptimizer:
    optimization_history = [{"device_ip": "10.0.0.2", "result": {"success": True}}]

    async def run_optimization_cycle(self):
        return None


@pytest.mark.asyncio
async def test_autonomous_cycle_observes_without_requiring_model():
    supervisor = AutonomousSupervisor(
        discovery=FakeDiscovery(), optimizer=FakeOptimizer(), interval=1
    )
    result = await supervisor.run_cycle()
    assert result["devices"] == 0
    assert result["cycles"]
