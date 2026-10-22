import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import demo


def row(number, date="2026-10-15", doi=""):
    return {
        "openalex_id": f"W{number}", "title": f"Work {number}",
        "publication_date": date, "doi": doi, "authors": "",
        "source": "", "type": "article",
        "openalex_url": f"https://openalex.org/W{number}",
    }


def work(number, date="2026-10-15", doi=None):
    return {"id": f"https://openalex.org/W{number}", "title": f"Work {number}",
            "publication_date": date, "doi": doi, "authorships": [],
            "primary_location": None, "type": "article"}


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "demo.csv"
        demo.save_rows_atomic(self.path, [row(i) for i in range(1, 21)])

    def test_get_next_20_skips_existing_ids_and_dois(self):
        original = demo.read_rows(self.path)
        candidates = [work(20), work(21, doi="https://doi.org/10.1/a")]
        candidates += [work(i, "2026-10-14") for i in range(22, 41)]
        with patch.object(demo, "fetch_page", return_value=candidates) as fetch:
            added = demo.add_next_batch(self.path)
        rows = demo.read_rows(self.path)
        self.assertEqual(len(added), 20)
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[:20], original)
        self.assertEqual(rows[20]["openalex_id"], "W21")
        self.assertEqual(fetch.call_args.args[:2], (None, "2026-10-15"))

    def test_repeated_clicks_move_to_older_date(self):
        batches = [[work(i, "2026-10-14") for i in range(21, 41)],
                   [work(i, "2026-10-13") for i in range(41, 61)]]
        with patch.object(demo, "fetch_page", side_effect=batches) as fetch:
            demo.add_next_batch(self.path)
            demo.add_next_batch(self.path)
        self.assertEqual(len(demo.read_rows(self.path)), 60)
        self.assertEqual(fetch.call_args.args[:2], (None, "2026-10-14"))

    def test_error_does_not_change_saved_csv(self):
        before = self.path.read_bytes()
        with patch.object(demo, "fetch_page", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                demo.add_next_batch(self.path)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
