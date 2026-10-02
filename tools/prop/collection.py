"""How a collection decides its length, one element at a time.

Every collection, a list, a dict or a repetition in a pattern, decodes the
same way: before each element a continue flag, an integer choice that
decides structure, then the element's own choices. The flag's bounds force
it while the count is below the minimum or at the maximum, so every replay
of recorded choices yields a length inside the sizes.

Each element is a span labelled ELEMENT, or ENTRY in a dict, that starts at
its flag. Deleting that span deletes the element whole.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from . import draw
from .case import Case, Rejected, Request

#: The span labels of one element of a collection and one entry of a dict.
ELEMENT: Final = "element"
ENTRY: Final = "entry"

#: A collection that discards this many duplicates in a row stops. A
#: collection still below its minimum size then rejects the case.
MAX_DISCARDS: Final = 10


@dataclass(frozen=True)
class Sizes:
    """The bounds on a collection's length, both inclusive.

    A max_size of None leaves the length unbounded, and the cap on choices
    per case bounds it instead.
    """

    min_size: int = 0
    max_size: int | None = None

    def __post_init__(self) -> None:
        """Refuse sizes that admit no length.

        Raises:
            ValueError: min_size is negative, or max_size is below it.
        """
        if self.min_size < 0 or (
            self.max_size is not None and self.max_size < self.min_size
        ):
            raise ValueError(
                f"prop: sizes [{self.min_size}, {self.max_size}] are empty"
            )

    @property
    def average(self) -> int:
        """Return the average length the random phase aims for."""
        return draw.average_length(self.min_size, self.max_size)


def more(case: Case, count: int, sizes: Sizes, *, stopped: bool = False) -> bool:
    """Return the case's decision whether a collection of count elements grows.

    The decision is an integer choice that decides structure, with the
    bounds draw.flag_bounds states. A stopped collection decides as one at
    its maximum would: the bounds admit only 0. The edge phase gives a
    collection one element: its edge is 1 at count 0 and 0 after.
    """
    lo, hi, average = sizes.min_size, sizes.max_size, sizes.average
    request = Request(
        draw.flag_bounds(count, lo, count if stopped else hi),
        lambda source: draw.flag(source, count, lo, count if stopped else hi, average),
        edge=1 if count == 0 else 0,
    )
    return case.choose(request) == 1


def collect[T](
    case: Case,
    sizes: Sizes,
    label: str,
    decode: Callable[[], tuple[T, object]],
    stop: Callable[[], bool] | None = None,
) -> list[T]:
    """Decode a collection: per element a continue flag, then the element.

    decode returns an element and the key it must be unique by, or None
    when the collection allows duplicates. An element whose key repeats an
    earlier key is discarded, and the next flag is decided for the same
    count. After MAX_DISCARDS discards in a row, the collection stops.

    stop, when given, is asked before each flag that the minimum size does
    not force. When it is true, the flag admits only 0, so the collection
    takes no further element.

    Raises:
        Rejected: the collection stopped below its minimum size.
    """
    items: list[T] = []
    seen: set[object] = set()
    discards = 0
    while True:
        start = len(case.choices)
        stopped = stop is not None and len(items) >= sizes.min_size and stop()
        if not more(case, len(items), sizes, stopped=stopped):
            return items
        with case.span(label, start):
            item, key = decode()
        if key is not None and key in seen:
            discards += 1
            if discards < MAX_DISCARDS:
                continue
            if len(items) < sizes.min_size:
                raise Rejected
            return items
        discards = 0
        seen.add(key)
        items.append(item)
