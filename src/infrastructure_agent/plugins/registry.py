"""Entry-point discovery for optional plugins.

A broken or partially installed plugin is logged and skipped; it must never
prevent the core CLI from starting.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from .base import Plugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "infrastructure_agent.plugins"
_REQUIRED_ATTRIBUTES = ("name", "description", "commands", "register_cli", "run")

_plugins: dict[str, Plugin] | None = None


def load_plugins(*, refresh: bool = False) -> dict[str, Plugin]:
    """Return installed plugins keyed by plugin name."""
    global _plugins
    if _plugins is not None and not refresh:
        return dict(_plugins)

    discovered: dict[str, Plugin] = {}
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded: Any = entry_point.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
            missing = [name for name in _REQUIRED_ATTRIBUTES if not hasattr(plugin, name)]
            if missing:
                raise TypeError(f"missing attributes: {', '.join(missing)}")
            discovered[plugin.name] = plugin
        except Exception as exc:
            logger.warning("Skipping plugin %s: %s", entry_point.name, exc)

    _plugins = discovered
    return dict(discovered)


def find_plugin(command: str) -> Plugin | None:
    """Return the plugin that owns ``command``, if any is installed."""
    for plugin in load_plugins().values():
        if command in plugin.commands:
            return plugin
    return None
