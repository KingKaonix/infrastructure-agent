from infrastructure_agent.core.config import AgentConfig
from infrastructure_agent.core.doctor import run_checks


def test_doctor_requires_explicit_network_and_ssh_trust(tmp_path):
    config = AgentConfig(tmp_path / "missing.json")
    result = run_checks(config)
    assert not result["ready"]
    assert not result["checks"]["network_range"]["ok"]
    assert not result["checks"]["ssh_known_hosts"]["ok"]
