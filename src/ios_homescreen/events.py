"""Progress events. The core never prints; it reports through an optional callback.

The CLI prints ``event.message``; a UI can stream ``event.to_dict()`` as JSON.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

INFO = "info"
WARNING = "warning"
ERROR = "error"


@dataclass(frozen=True)
class Event:
    code: str
    """Stable machine-readable name, for example ``backup_saved``."""
    message: str
    """One human-readable sentence."""
    step: int | None = None
    total: int | None = None
    level: str = INFO
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step": self.step,
            "total": self.total,
            "level": self.level,
            "data": {k: str(v) if hasattr(v, "__fspath__") else v for k, v in self.data.items()},
        }


EventSink = Callable[[Event], None]


def ignore(event: Event) -> None:
    """Default sink: drop events."""
