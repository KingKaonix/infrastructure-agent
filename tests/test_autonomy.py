import pytest

from infrastructure_agent.autonomy import AutonomousSupervisor
from infrastructure_agent.core.audit import AuditLog


class FakeDiscovery:
    def get_all_devices(self):
        return {}

    async def discover_network(self):
        return None


class FakeOptimizer:
    optimization_history = [{"device_ip": "10.0.0.2", "result": {"success": True}}]

    async def run_optimization_cycle(self):
        return None


class FakeAI:
    async def process_request(self, *_args):
        return "review complete"


@pytest.mark.asyncio
async def test_autonomous_cycle_observes_without_requiring_model():
    supervisor = AutonomousSupervisor(
        discovery=FakeDiscovery(), optimizer=FakeOptimizer(), interval=1
    )
    result = await supervisor.run_cycle()
    assert result["devices"] == 0
    assert result["cycles"]


@pytest.mark.asyncio
async def test_autonomous_ai_review_is_persisted(tmp_path):
    audit = AuditLog(tmp_path / "agent.db")
    supervisor = AutonomousSupervisor(
        discovery=FakeDiscovery(),
        optimizer=FakeOptimizer(),
        ai_layer=FakeAI(),
        deployer=object(),
        ssh=object(),
        audit=audit,
        interval=1,
    )

    result = await supervisor.run_cycle()

    assert result["ai_review"] == "review complete"
    events = audit.list()
    assert events[0]["action"] == "ai.review"
    assert events[0]["outcome"] == "success"
