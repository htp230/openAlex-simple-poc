import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector


class CollectorTests(unittest.TestCase):
    def test_doi_normalization_and_deduplication(self):
        works = [
            {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/ABC"},
            {"id": "https://openalex.org/W2", "doi": "doi:10.1234/abc"},
            {"id": "https://openalex.org/W3", "doi": None},
            {"id": "https://openalex.org/W3", "doi": None},
        ]
        self.assertEqual([w["id"] for w in collector.unique_works(works)], [works[0]["id"], works[2]["id"]])

    def test_row_handles_missing_optional_data(self):
        row = collector.to_row({"id": "https://openalex.org/W1", "title": "Example", "authorships": []})
        self.assertEqual(row["title"], "Example")
        self.assertEqual(row["openalex_id"], "W1")
        self.assertEqual(row["authors"], "")
        self.assertEqual(row["source"], "")

    def test_collect_pages_until_20_unique(self):
        first = [{"id": f"https://openalex.org/W{i}", "doi": None} for i in range(19)]
        first.extend(first[:1] * 31)  # A full API page with repeated records.
        second = [{"id": "https://openalex.org/W20", "doi": None}]
        with patch.object(collector, "fetch_page", side_effect=[first, second]) as fetch:
            works = collector.collect(limit=20)
        self.assertEqual(len(works), 20)
        self.assertEqual(fetch.call_count, 2)

    def test_writes_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "publications.csv"
            collector.write_csv([{"id": "https://openalex.org/W1", "title": "Example"}], path)
            with path.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Example")


if __name__ == "__main__":
    unittest.main()
