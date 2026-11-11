import pytest
from fastapi.testclient import TestClient

from infrastructure_agent.api import create_app
from infrastructure_agent.telegram import parse_command


def test_telegram_commands_parse_bot_suffix():
    command = parse_command("/status@infra_bot")
    assert command.name == "/status"
    assert command.arguments == ()


def test_telegram_rejects_plain_text():
    with pytest.raises(ValueError):
        parse_command("hello")


class EmptyDiscovery:
    def get_all_devices(self):
        return {}


def test_health_and_status_api_are_available():
    client = TestClient(create_app(discovery=EmptyDiscovery()))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/status").json() == {"devices": [], "count": 0}
