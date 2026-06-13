from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def batches(items: list[T], size: int) -> list[list[T]]:
    """Split a list into sub-lists of the given size (the last batch may be smaller)."""
    return [items[index : index + size] for index in range(0, len(items), size)]
