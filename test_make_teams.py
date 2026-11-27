"""Tests for make_teams.py. Run: python -m unittest test_make_teams"""

import json
import os
import unittest
from unittest import mock

import make_teams as mt

HISTORY = """
2026-11-04
Red (5): Ann, Bob, Cid, Dan, Eve
Blue (3): Fay, Gus, Hal, Ivy, Jon

2026-10-28
Red (2): Ann, Fay, Cid, Hal, Eve
Blue (4): Bob, Gus, Dan, Ivy, Jon
"""

RATINGS = """
# name | position | tier | never with
Ann | defender   | 1 | Bob
Bob | striker    | 1 |
Cid | defender   | 2 |
Dan | striker    | 2 |
Eve | allrounder | 3 |
Fay | defender   | 3 |
Gus | striker    | 4 |
Hal | allrounder | 4 |
Ivy | allrounder | 2 |
Jon | allrounder | 3 |
"""


def run(names, ratings_text=RATINGS, history_text=HISTORY):
    matches, _ = mt.parse_match_file(history_text)
    ratings, _ = mt.parse_ratings(ratings_text)
    players = mt.build_players(names, mt.player_history(matches), ratings)
    return players, mt.suggest(players, mt.played_together(matches))


def team_names(team):
    return {p.name for p in team}


class TeamTests(unittest.TestCase):
    def test_never_together_is_respected_both_ways(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay", "Gus", "Hal", "Ivy", "Jon"])
        for option in options:
            for team in (option.red, option.blue):
                self.assertFalse({"Ann", "Bob"} <= team_names(team))

    def test_positions_and_tiers_are_balanced(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay", "Gus", "Hal", "Ivy", "Jon"])
        best = options[0]
        self.assertEqual(best.red_m.defenders + best.blue_m.defenders, 3)
        self.assertLessEqual(abs(best.red_m.defenders - best.blue_m.defenders), 1)
        self.assertLessEqual(abs(best.red_m.strikers - best.blue_m.strikers), 1)
        self.assertLessEqual(abs(best.red_m.strength - best.blue_m.strength), 1)

    def test_names_match_ignoring_case_and_accents(self):
        players, _ = run(["ANN", "böb", "Cid", "Dan"])
        self.assertEqual([p.name for p in players], ["Ann", "Bob", "Cid", "Dan"])
        self.assertTrue(all(p.tier_source == "rated" for p in players))

    def test_unrated_players(self):
        players, _ = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Newbie"], ratings_text="Ann | defender | 1")
        by_name = {p.name: p for p in players}
        self.assertEqual(by_name["Bob"].tier_source, "estimated")
        self.assertEqual(by_name["Newbie"].tier_source, "default")
        self.assertEqual(by_name["Newbie"].tier, mt.DEFAULT_TIER)

    def test_odd_number_of_players(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay", "Gus"])
        self.assertEqual({len(options[0].red), len(options[0].blue)}, {3, 4})

    def test_odd_number_smaller_team_gets_stronger_players(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay", "Gus", "Hal", "Ivy"])
        best = options[0]
        small, big = sorted((best.red, best.blue), key=len)

        def avg(team):  # lower tier = better
            return sum(p.tier for p in team) / len(team)

        self.assertLess(avg(small), avg(big))
        self.assertLessEqual(abs(best.red_m.strength - best.blue_m.strength), 1)

    def test_few_matches_count_less(self):
        one_lucky_win = HISTORY + "\n2026-10-21\nRed (9): Ann, Bob, Cid, Dan, Zoe\nBlue (0): Eve, Fay, Gus, Hal, Ivy\n"
        players, _ = run(["Zoe", "Ann", "Bob", "Cid"], ratings_text="", history_text=one_lucky_win)
        zoe = next(p for p in players if p.name == "Zoe")
        self.assertLess(zoe.ppm, 2.0)  # raw would be 3.00 from a single win
        self.assertGreater(zoe.ppm, 1.0)

    def test_json_output_has_only_the_teams(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay"])
        data = json.loads(mt.as_json("2026-11-25", options, []))
        self.assertEqual(len(data["options"]), 3)
        first = data["options"][0]
        self.assertEqual(set(first), {"red", "blue", "whatsapp_text", "whatsapp_link"})
        self.assertTrue(first["whatsapp_link"].startswith("https://wa.me/?text="))

    def test_whatsapp_message_never_contains_ratings(self):
        _, options = run(["Ann", "Bob", "Cid", "Dan", "Eve", "Fay"])
        text = mt.whatsapp_text("2026-11-25", options[0])
        self.assertNotRegex(text.lower(), r"tier|defender|striker|allrounder")
        self.assertIn("Wed 25 Nov", text)
        self.assertNotIn("http", text)  # just the teams, no links
        self.assertEqual(len(text.splitlines()), 3)

    def test_secret_overrides_file(self):
        with mock.patch.dict(os.environ, {"PLAYER_RATINGS": "Zed | striker | 4"}):
            ratings, _, source = mt.load_ratings()
        self.assertEqual(source, "PLAYER_RATINGS secret")
        self.assertIn("zed", ratings)

    def test_bad_lines_are_skipped_with_a_warning(self):
        text = "\n".join(["Ann | defender | 6", "Bob | goalie | 2", "Cid", "Dan | striker | 2"])
        ratings, warnings = mt.parse_ratings(text)
        self.assertEqual(list(ratings), ["dan"])
        self.assertEqual(len(warnings), 3)
        self.assertTrue(all(w.startswith("line ") for w in warnings))
        self.assertFalse(any("Ann" in w or "Bob" in w for w in warnings))  # never echo the line

    def test_decimal_tiers(self):
        text = "\n".join(["Ann | defender | 1.5", "Bob | 3.75", "Cid | 2,5", "Dan | 4.5"])
        ratings, warnings = mt.parse_ratings(text)
        self.assertEqual([ratings[k].tier for k in ("ann", "bob", "cid")], [1.5, 3.75, 2.5])
        self.assertNotIn("dan", ratings)  # above 4 is not allowed
        self.assertEqual(len(warnings), 1)

    def test_short_form_name_and_tier(self):
        ratings, _ = mt.parse_ratings("New Guy | 2")
        self.assertEqual((ratings["new guy"].position, ratings["new guy"].tier), ("allrounder", 2.0))


if __name__ == "__main__":
    unittest.main()
