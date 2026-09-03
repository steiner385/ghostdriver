"""The tool surface, as plain functions returning plain data.

Deliberately separate from the MCP binding. The protocol layer is a thin
adapter over this; everything that could be wrong — a tier not enforced, a
result that blows a context budget, an error that says nothing useful — is
wrong here, and can be tested here without a protocol client.

Two rules shape every result.

**Locators, not handles.** A handle is valid only for the enumeration that
produced it: the OS recycles them, and one held across a call answers about
a window that no longer exists. Every element carries a locator that can be
re-resolved instead. Handles are still reported, marked ephemeral, because
they are what makes two same-captioned controls distinguishable in a single
result — but nothing should store one.

**Results are for an agent's context, not a file.** A target with ~1,100
windows can answer almost any query with more than a caller can read.
Everything that can return many rows caps them and says what it capped.
"""

from .actuation import ActuationTools
from .core import MAX_ELEMENTS, SENSITIVE_HINT, _element, _error
from .discovery import DiscoveryTools
from .human import HumanTools
from .learning import LearningTools
from .lifecycle import LifecycleTools
from .status import StatusTools

__all__ = ["MAX_ELEMENTS", "SENSITIVE_HINT", "Toolbox", "_element", "_error"]


class Toolbox(LifecycleTools, DiscoveryTools, StatusTools, ActuationTools,
              HumanTools, LearningTools):
    """Every tool, over one session manager.

    One class, so a caller holds one object; one module per family, so a
    reader opens the file named for what they are looking at. The
    dataclass fields and every shared helper live on `_ToolboxCore`.
    """
