"""Offline tests for sunday_check.py. Run: python -m unittest test_sunday_check"""

import unittest
from urllib.parse import unquote

import sunday_check as sc

MATCHES = """
2026-11-18
Red (5): Ann, Bob, Cid
Blue (3): Dan, Eve, Fay

2026-11-11
Red (2): Ann, Gus, Hal
Blue (4): Ivy, Jon, Kim

2026-08-19
Red (1): Old, Ann, Bob
Blue (2): Dan, Eve, Fay
"""


class SundayCheckTests(unittest.TestCase):
    def test_suggestions_skip_going_and_waitlist(self):
        picks = sc.suggestions(MATCHES, exclude=["ann", "BOB", "Eve"], since=None)
        names = [p["name"] for p in picks]
        self.assertNotIn("Ann", names)
        self.assertNotIn("Bob", names)
        self.assertNotIn("Eve", names)
        self.assertEqual(set(names[:3]), {"Cid", "Dan", "Fay"})  # the rest of last week's players

    def test_regulars_first(self):
        picks = sc.suggestions(MATCHES, exclude=[], since=None)
        self.assertEqual(picks[0]["name"], "Ann")  # 3 matches
        self.assertEqual({p["name"] for p in picks[1:5]}, {"Bob", "Dan", "Eve", "Fay"})  # 2 each
        counts = [p["matches"] for p in picks]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_short_meetup_name_matches_full_name(self):
        text = "2026-11-18\nRed (1): Manzur Mukhitdinov, Ann\nBlue (2): Bob, Cid\n"
        names = [p["name"] for p in sc.suggestions(text, exclude=["Manzur"], since=None)]
        self.assertNotIn("Manzur Mukhitdinov", names)
        self.assertIn("Ann", names)  # "Ann" is not excluded by e.g. "Anne"

    def test_only_this_season(self):
        picks = sc.suggestions(MATCHES, exclude=[], since="2026-08-26")
        self.assertNotIn("Old", [p["name"] for p in picks])

    def test_message(self):
        text = sc.message("2026-11-25", 9, 12, ["Gus", "Hal"], "https://www.meetup.com/x/")
        self.assertIn("Wed 25 Nov", text)
        self.assertIn("9/12", text)
        self.assertIn("Gus, Hal", text)
        self.assertIn("https://www.meetup.com/x/", text)
        self.assertIn("Gus", unquote(sc.whatsapp_link(text)))


if __name__ == "__main__":
    unittest.main()
