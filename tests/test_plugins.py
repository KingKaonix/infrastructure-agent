import pytest

from infrastructure_agent.plugins import registry


class FakePlugin:
    name = "fake"
    description = "Fake plugin"
    commands = ("fake",)

    def register_cli(self, subparsers):
        subparsers.add_parser("fake", help=self.description)

    async def run(self, command, args, services):
        return 0


class FakeEntryPoint:
    name = "fake"

    def __init__(self, loaded):
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


def test_load_plugins_returns_installed_plugins(monkeypatch):
    monkeypatch.setattr(registry, "entry_points", lambda **_kwargs: [FakeEntryPoint(FakePlugin)])
    plugins = registry.load_plugins(refresh=True)
    assert plugins["fake"].description == "Fake plugin"
    assert registry.find_plugin("fake") is plugins["fake"]


def test_broken_plugin_is_skipped(monkeypatch):
    class IncompletePlugin:
        name = "broken"

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **_kwargs: [
            FakeEntryPoint(IncompletePlugin),
            FakeEntryPoint(RuntimeError("import failed")),
        ],
    )
    assert registry.load_plugins(refresh=True) == {}


def test_unknown_command_has_no_plugin(monkeypatch):
    monkeypatch.setattr(registry, "entry_points", lambda **_kwargs: [])
    assert registry.find_plugin("telegram") is None


@pytest.fixture(autouse=True)
def _reset_registry():
    registry._plugins = None
    yield
    registry._plugins = None
