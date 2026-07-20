"""Python strategy plugins (doc §8.6).

Drop a module here that defines ``register(registry)`` and calls
``registry.register_primitive(name, fn)`` to add a custom decision type to the rule
grammar. ``app.strategy.plugin_loader.load_plugins`` imports every module in this
package and wires it up — no restart needed.
"""
