"""Spectre — the fastest X/Twitter automation for AI agents."""

from spectre.logsetup import configure as _configure_logging

_configure_logging()

__version__ = "2.0.1"


def __getattr__(name):
    # Keep `from spectre import mcp` working without importing FastMCP (and the
    # whole tool registry) for CLI-only commands like `spectre add`.
    if name == "mcp":
        from spectre.server import mcp as _mcp

        return _mcp
    raise AttributeError(name)


__all__ = ["mcp", "__version__"]
