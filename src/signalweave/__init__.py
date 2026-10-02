"""SignalWeave semantic decision layer."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("signal-weave")
except PackageNotFoundError:
    __version__ = "uninstalled"
