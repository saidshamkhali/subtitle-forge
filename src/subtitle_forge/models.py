from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import timedelta


@dataclass(frozen=True)
class SubtitleCue:
    id: str
    start: timedelta
    end: timedelta
    text: str

    def with_text(self, text: str) -> SubtitleCue:
        return replace(self, text=text)
