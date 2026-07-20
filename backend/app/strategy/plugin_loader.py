"""Load Python strategy plugins from ``strategy/plugins/`` (doc §8.6, hot-reload).

Each plugin module exposes a module-level ``register(registry)`` that adds custom
primitives. :func:`load_plugins` (re)imports every module in the package and calls
its ``register`` — so dropping a new file in (or editing one) and re-running the
loader makes the new decision type available with no process restart. The bot and
an API endpoint both call this, which is the "plugin files are watcher-loaded"
half of §8.6's hot-reload promise.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from app.strategy.plugin_registry import PluginRegistry, get_plugin_registry

logger = logging.getLogger(__name__)

_PLUGIN_PACKAGE = "app.strategy.plugins"


def load_plugins(registry: PluginRegistry | None = None) -> list[str]:
    """(Re)load every plugin module; return the names of plugins registered.

    Idempotent: the registry is cleared first so a reload reflects deletions and
    edits, not just additions. Failures in one plugin are logged and skipped so a
    single bad file cannot take down the loader.
    """
    reg = registry or get_plugin_registry()
    reg.clear()

    package = importlib.import_module(_PLUGIN_PACKAGE)
    loaded: list[str] = []
    for mod_info in pkgutil.iter_modules(package.__path__):
        if mod_info.name.startswith("_"):
            continue
        full_name = f"{_PLUGIN_PACKAGE}.{mod_info.name}"
        try:
            module = importlib.import_module(full_name)
            module = importlib.reload(module)  # pick up edits on hot-reload
            register = getattr(module, "register", None)
            if callable(register):
                register(reg)
                loaded.append(mod_info.name)
            else:
                logger.warning("plugin %s has no register(registry)", full_name)
        except Exception as exc:  # pragma: no cover - resilience
            logger.warning("plugin %s failed to load: %s", full_name, exc)
    logger.info("loaded %d strategy plugin(s): %s", len(loaded), ", ".join(loaded) or "-")
    return loaded
