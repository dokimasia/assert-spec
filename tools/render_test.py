"""The renderer: the vectors on disk are the reference's, and a clash is refused."""

from __future__ import annotations

import unittest
from typing import final

from prop.vectors import KINDS
from render import VECTORS, RenderError, vector, vectors_text


@final
class VectorsTest(unittest.TestCase):
    """The vector files and the function that renders one case."""

    def test_every_vector_file_is_what_the_reference_renders(self) -> None:
        """A vector the reference no longer computes fails here, tracked or not."""
        for kind in KINDS:
            with self.subTest(kind=kind):
                on_disk = (VECTORS / f"{kind}.json").read_text()
                self.assertEqual(on_disk, vectors_text(kind), "run make render")

    def test_a_case_keeps_its_inputs_and_gains_the_outputs(self) -> None:
        """The inputs first, in their order, then the outputs."""
        case = {"id": "coverage/met", "counted": 27, "valid": 100, "share": 0.1}
        rendered = vector("coverage", {**case, "last": False, "exact": False})
        self.assertEqual(
            list(rendered),
            ["id", "counted", "valid", "share", "last", "exact", "verdict"],
        )
        self.assertEqual(rendered["verdict"], "met")

    def test_an_input_named_as_an_output_is_refused(self) -> None:
        """An output never replaces what the YAML states."""
        case = {"id": "token/encodes", "choices": [], "token": "prop1:AAA"}
        with self.assertRaisesRegex(RenderError, "token"):
            vector("token", case)

    def test_a_case_that_is_not_an_object_is_refused(self) -> None:
        """A YAML list item that is a scalar names no inputs."""
        with self.assertRaises(RenderError):
            vector("token", "token/encodes")
