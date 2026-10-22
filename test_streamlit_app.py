import csv
import io
import sys
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import collector
import streamlit_app


def row(number, published="2026-10-15", doi=""):
    return {
        "openalex_id": f"W{number}", "title": f"Work {number}",
        "publication_date": published, "doi": doi, "authors": "",
        "source": "", "type": "article",
        "openalex_url": f"https://openalex.org/W{number}",
    }


def work(number, published="2026-10-15", doi=None):
    return {
        "id": f"https://openalex.org/W{number}", "title": f"Work {number}",
        "publication_date": published, "doi": doi, "authorships": [],
        "primary_location": None, "type": "article",
    }


class StreamlitAppTests(unittest.TestCase):
    def fake_streamlit(self, button_results):
        st = MagicMock()
        st.session_state = {}
        st.button.side_effect = button_results
        st.spinner.return_value = nullcontext()
        return st

    def test_seed_has_original_20_rows(self):
        rows = streamlit_app.read_seed_rows()
        self.assertEqual(len(rows), 20)
        self.assertEqual(list(rows[0]), list(collector.HEADERS))
        self.assertEqual(rows[0]["openalex_id"], "W7223134565")

    def test_inclusive_cutoff_and_deduplication_by_id_and_doi(self):
        rows = [row(1, doi="10.1/old"), row(2)]
        candidates = [
            work(1),
            work(3, doi="https://doi.org/10.1/OLD"),
            work(4, published="2026-10-16"),
            work(5, doi="https://doi.org/10.1/new"),
            work(6, doi="doi:10.1/NEW"),
            work(7, published="2026-10-14"),
        ]
        with patch.object(collector, "fetch_page", return_value=candidates) as fetch:
            added = streamlit_app.next_older_rows(rows)
        self.assertEqual([item["openalex_id"] for item in added], ["W5", "W7"])
        self.assertEqual(fetch.call_args.args[:3], (None, "2026-10-15", 1))
        self.assertEqual(len(rows), 2)

    def test_repeated_batches_move_to_older_date(self):
        rows = [row(i) for i in range(1, 21)]
        batches = [
            [work(i, "2026-10-14") for i in range(21, 41)],
            [work(i, "2026-10-13") for i in range(41, 61)],
        ]
        with patch.object(collector, "fetch_page", side_effect=batches) as fetch:
            rows += streamlit_app.next_older_rows(rows)
            rows += streamlit_app.next_older_rows(rows)
        self.assertEqual(len(rows), 60)
        self.assertEqual(fetch.call_args.args[:2], (None, "2026-10-14"))

    def test_pages_past_full_duplicate_page(self):
        rows = [row(1)]
        first = [work(1)] * 100
        second = [work(2, "2026-10-14")]
        with patch.object(collector, "fetch_page", side_effect=[first, second]) as fetch:
            added = streamlit_app.next_older_rows(rows)
        self.assertEqual([item["openalex_id"] for item in added], ["W2"])
        self.assertEqual(fetch.call_count, 2)

    def test_partial_and_empty_results(self):
        rows = [row(1)]
        with patch.object(collector, "fetch_page", return_value=[work(2)]):
            self.assertEqual(len(streamlit_app.next_older_rows(rows)), 1)
        with patch.object(collector, "fetch_page", return_value=[]):
            self.assertEqual(streamlit_app.next_older_rows(rows), [])

    def test_fetch_error_leaves_existing_rows_unchanged(self):
        rows = [row(1)]
        original = [item.copy() for item in rows]
        first = [work(2)] * 100
        with patch.object(collector, "fetch_page", side_effect=[first, RuntimeError("offline")]):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                streamlit_app.next_older_rows(rows)
        self.assertEqual(rows, original)

    def test_csv_download_contains_current_rows(self):
        rows = [row(1), row(2, "2026-10-14")]
        data = streamlit_app.csv_bytes(rows)
        parsed = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(parsed, rows)
        self.assertEqual(len(parsed), 2)

    def test_session_starts_from_seed_and_click_updates_table_and_download(self):
        st = self.fake_streamlit([False, True])
        new_rows = [row(i, "2026-10-14") for i in range(21, 41)]
        with patch.dict(sys.modules, {"streamlit": st}), \
             patch.object(streamlit_app, "next_older_rows", return_value=new_rows):
            streamlit_app.main()
            streamlit_app.main()
        self.assertEqual(st.metric.call_args_list[0].args, ("Total publications", 20))
        self.assertEqual(st.metric.call_args_list[1].args, ("Total publications", 40))
        self.assertEqual(len(st.session_state["publications"]), 40)
        self.assertEqual(len(st.dataframe.call_args.args[0]), 40)
        download = st.download_button.call_args.kwargs["data"]
        self.assertEqual(len(list(csv.DictReader(io.StringIO(download.decode("utf-8-sig"))))), 40)

    def test_session_keeps_rows_on_fetch_error(self):
        st = self.fake_streamlit([True])
        with patch.dict(sys.modules, {"streamlit": st}), \
             patch.object(streamlit_app, "next_older_rows", side_effect=RuntimeError("offline")):
            streamlit_app.main()
        self.assertEqual(len(st.session_state["publications"]), 20)
        st.error.assert_called_once()
        self.assertEqual(st.metric.call_args.args, ("Total publications", 20))


if __name__ == "__main__":
    unittest.main()
