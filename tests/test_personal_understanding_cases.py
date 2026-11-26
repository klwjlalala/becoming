import json
import unittest
from datetime import date
from pathlib import Path

from evaluation.personal_understanding import DatedSQLiteConversationStore


FIXTURE = Path(__file__).parents[1] / "evaluation" / "personal_understanding_cases.json"


class PersonalUnderstandingFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_has_exactly_thirty_chronological_turns(self):
        turns = self.data["turns"]
        self.assertEqual(len(turns), 30)
        days = [date.fromisoformat(turn["day"]) for turn in turns]
        self.assertEqual(days, sorted(days))
        self.assertEqual(len(set(days)), len(days))

    def test_simulated_fixture_day_is_persisted_as_turn_timestamp(self):
        store = DatedSQLiteConversationStore()
        try:
            store.simulated_day = "2024-01-10"
            turn_id = store.append_turn("用户原话", "助手回复")
            row = store.connection.execute(
                "SELECT created_at FROM turns WHERE id=?", (turn_id,)
            ).fetchone()
            self.assertEqual(row[0], "2024-01-10T12:00:00+00:00")
        finally:
            store.close()

    def test_evidence_quotes_are_source_bound_and_labels_unique(self):
        labels = set()
        for turn in self.data["turns"]:
            self.assertIsInstance(turn["text"], str)
            self.assertTrue(turn["text"].strip())
            evidence = turn.get("evidence", [])
            if turn.get("no_write"):
                self.assertEqual(evidence, [])
            for item in evidence:
                self.assertNotIn(item["label"], labels)
                labels.add(item["label"])
                self.assertTrue(item["quote"])
                self.assertIn(item["quote"], turn["text"])

    def test_fixture_covers_required_longitudinal_capabilities(self):
        self.assertTrue(self.data["fictional"])
        self.assertGreaterEqual(len(self.data["expected_understandings"]), 5)
        self.assertGreaterEqual(len(self.data["review_criteria"]), 8)
        required = set(self.data["required_capabilities"])
        self.assertTrue({
            "explicit_correction", "contextual_contradiction", "goal_change",
            "self_reinterpretation", "natural_retrieval", "no_irrelevant_retrieval",
        } <= required)

    def test_noise_and_final_synthesis_are_present(self):
        turns = self.data["turns"]
        self.assertTrue(any("我朋友" in t["text"] for t in turns))
        self.assertTrue(any("假设" in t["text"] for t in turns))
        self.assertTrue(any("Python" in t["text"] for t in turns))
        self.assertTrue(turns[-1].get("no_write"))
        self.assertIn("真正想要的生活", turns[-1]["text"])


if __name__ == "__main__":
    unittest.main()
