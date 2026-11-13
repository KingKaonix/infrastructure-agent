import pytest

from infrastructure_agent_telegram import TelegramCommandHandler, parse_command
from infrastructure_agent_telegram.transport import compact_payload


def test_commands_parse_bot_suffix():
    command = parse_command("/status@infra_bot")
    assert command.name == "/status"
    assert command.arguments == ()


def test_plain_text_is_rejected():
    with pytest.raises(ValueError):
        parse_command("hello")


class FakeDevice:
    def to_dict(self):
        return {"ip": "192.168.12.42"}


class FakeDiscovery:
    def get_all_devices(self):
        return {"192.168.12.42": FakeDevice()}

    async def discover_network(self):
        return None


class FakeOptimizer:
    async def optimize_device(self, _device):
        raise AssertionError("not used")


def _handler() -> TelegramCommandHandler:
    return TelegramCommandHandler(
        discovery=FakeDiscovery(), ssh=object(), deployer=object(), optimizer=FakeOptimizer()
    )


@pytest.mark.asyncio
async def test_help_returns_markdown_text():
    result = await _handler().handle("/help")
    assert isinstance(result, str)
    assert "/help" in result


@pytest.mark.asyncio
async def test_status_returns_structured_payload():
    result = await _handler().handle("/status")
    assert result == {"ok": True, "devices": [{"ip": "192.168.12.42"}]}


def test_compact_payload_drops_unset_optional_fields():
    assert compact_payload({"chat_id": "1", "text": "hi", "parse_mode": None}) == {
        "chat_id": "1",
        "text": "hi",
    }
