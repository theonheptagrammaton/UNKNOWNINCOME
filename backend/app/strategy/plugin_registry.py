"""Registry for plugin-contributed signal primitives (doc §8.6, Python layer).

The rule grammar has six built-in primitives (§5.4). A Python plugin can add new
*decision types* by registering a primitive here: a pure function mapping resolved
operands + the clause's ``args`` to a boolean Series. The rule engine consults this
registry whenever a clause names a primitive it doesn't recognise, so plugins slot
into the exact same evaluation path as the built-ins — no fork, no special-casing.

Lookahead safety (rule #1) is the plugin author's contract: like every built-in, a
custom primitive must depend only on bars ``≤ t`` (use ``.shift(1)`` for crossings,
never ``.shift(-1)``).
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

# A custom primitive: (operand_name → aligned Series, clause args) → boolean Series.
CustomPrimitive = Callable[[dict[str, "pd.Series"], dict], "pd.Series"]


class PluginRegistry:
    """Process-wide store of plugin-registered primitives (hot-reloadable)."""

    def __init__(self) -> None:
        self._primitives: dict[str, CustomPrimitive] = {}

    def register_primitive(self, name: str, fn: CustomPrimitive) -> None:
        """Register (or replace) a custom primitive by name."""
        if not name or not callable(fn):
            raise ValueError("register_primitive needs a name and a callable")
        self._primitives[name] = fn

    def get_primitive(self, name: str) -> CustomPrimitive | None:
        return self._primitives.get(name)

    def names(self) -> list[str]:
        return sorted(self._primitives)

    def clear(self) -> None:
        self._primitives.clear()


_REGISTRY = PluginRegistry()


def get_plugin_registry() -> PluginRegistry:
    """The singleton plugin registry the rule engine and loader share."""
    return _REGISTRY
