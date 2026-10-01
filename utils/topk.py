"""Bounded heap for Top-K selection.

Keeping a min-heap of size K means each of N candidates costs O(log K) instead of
sorting all N items (O(N log N)). Ties are broken deterministically by item id.
"""
import heapq
from typing import Any, Iterable, List, Tuple


class _Entry:
    """Heap entry ordered so the *worst* candidate sits at the root of the min-heap."""
    __slots__ = ("score", "item_id", "value", "extra")

    def __init__(self, score, item_id, value, extra):
        self.score, self.item_id, self.value, self.extra = score, item_id, value, extra

    def __lt__(self, other: "_Entry") -> bool:
        if self.score != other.score:
            return self.score < other.score
        return self.item_id > other.item_id      # on equal score, the larger id is "worse"


class TopKHeap:
    def __init__(self, k: int, largest: bool = True):
        if not isinstance(k, int) or k < 1:
            raise ValueError("K must be a positive whole number.")
        self._k = k
        self._largest = largest
        self._heap: List[_Entry] = []

    def push(self, item_id: str, value: float, extra: Any = None) -> None:
        score = value if self._largest else -value
        entry = _Entry(score, item_id, value, extra)
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entry)
        elif self._heap[0] < entry:                  # better than the current worst
            heapq.heapreplace(self._heap, entry)

    def extend(self, items: Iterable[Tuple[str, float, Any]]) -> "TopKHeap":
        for item_id, value, extra in items:
            self.push(item_id, value, extra)
        return self

    def result(self) -> List[Tuple[str, float, Any]]:
        """Best-first list of (id, value, extra)."""
        ordered = sorted(self._heap, key=lambda e: (-e.score, e.item_id))
        return [(e.item_id, e.value, e.extra) for e in ordered]
