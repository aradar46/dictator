"""Run with python3 -m unittest tests.test_shortcuts (no GTK/GStreamer needed)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "dictator"))

from shortcuts import clean_trigger


class CleanTriggerTest(unittest.TestCase):
    def test_default_when_empty(self):
        self.assertEqual(clean_trigger(None), "Ctrl+Alt+A")
        self.assertEqual(clean_trigger(""), "Ctrl+Alt+A")

    def test_strips_press_prefix(self):
        self.assertEqual(clean_trigger("Press <Control><Alt>a"), "Ctrl+Alt+A")

    def test_translates_modifier_tokens(self):
        self.assertEqual(clean_trigger("<Super>space"), "Super+space")
        self.assertEqual(clean_trigger("<Shift><Meta>f"), "Shift+Meta+F")

    def test_uppercases_only_final_key(self):
        self.assertEqual(clean_trigger("<Control>b"), "Ctrl+B")

    def test_passthrough_for_unrecognized_format(self):
        self.assertEqual(clean_trigger("F12"), "F12")


if __name__ == "__main__":
    unittest.main()
