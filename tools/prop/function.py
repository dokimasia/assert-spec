"""The functions of the definition's subject kinds that take one input.

A property form's function subject and the map generator of the vectors
take the function of a subject kind. Each behaves as its summary in the
definition's subjects table states.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

#: The functions of the generated input, by subject kind.
FUNCTIONS: Final[dict[str, Callable[[Any], object]]] = {
    "identity": lambda x: x,
    "is-non-negative": lambda x: x >= 0,
    "returns-null": lambda x: None,
    "drops-the-first": lambda x: x[1:],
    "prepends-zero": lambda x: [0, *x],
    "sorts": sorted,
    "wraps-in-a-and-b": lambda x: f"a{x}b",
}
