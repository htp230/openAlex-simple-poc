import csv
import io
import sys
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import collector
import streamlit_app


class RerunRequested(Exception):
    pass


class StopRequested(Exception):
    pass


def row(number, published="2026-10-15", doi=""):
    return {
        "openalex_id": f"W{number}", "title": f"Work {number}",
        "publication_date": published, "doi": doi, "authors": "",
        "source": "", "type": "article",
        "openalex_url": f"https://openalex.org/W{number}",
        "topic": "", "subfield": "", "field": "", "domain": "",
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
        st.components.v2.component.return_value.return_value.snapshot = {
            "status": "ready", "payload": None,
        }
        st.rerun.side_effect = RerunRequested
        st.stop.side_effect = StopRequested
        return st

    def test_seed_has_original_20_rows(self):
        rows = streamlit_app.read_seed_rows()
        self.assertEqual(len(rows), 20)
        self.assertEqual(list(rows[0]), list(collector.HEADERS))
        self.assertEqual(rows[0]["openalex_id"], "W7223134565")
        self.assertEqual(rows[0]["topic"], "Music History and Culture")
        self.assertEqual(rows[0]["subfield"], "Music")
        self.assertEqual(rows[0]["field"], "Arts and Humanities")
        self.assertEqual(rows[0]["domain"], "Social Sciences")

    def test_old_session_fills_seed_topics_without_changing_added_rows(self):
        seed = streamlit_app.read_seed_rows()
        old_session = [{key: value for key, value in item.items()
                        if key not in collector.TOPIC_HEADERS} for item in seed]
        old_session[0]["topic"] = ""
        added = row(999, "2026-10-14")
        added["topic"] = "Added work topic"
        old_session.append(added)
        filled = streamlit_app.fill_seed_classifications(old_session, seed)
        self.assertEqual(len(filled), 21)
        self.assertEqual(filled[0]["topic"], "Music History and Culture")
        self.assertEqual(filled[0]["domain"], "Social Sciences")
        self.assertEqual(filled[-1], added)
        self.assertEqual(old_session[0]["topic"], "")

    def test_browser_snapshot_restores_40_added_rows_and_skips_duplicates(self):
        seed = streamlit_app.read_seed_rows()
        added = [row(i, "2026-10-14") for i in range(100, 140)]
        payload = {"version": 1, "added": added + [added[0], row(999, "bad-date")]}
        restored = streamlit_app.restore_browser_rows(seed, payload)
        self.assertEqual(len(restored), 60)
        self.assertEqual(restored[20]["openalex_id"], "W100")
        self.assertEqual(restored[-1]["openalex_id"], "W139")
        self.assertEqual(len(streamlit_app.added_rows(restored, seed)), 40)

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

    def test_table_numbers_and_clickable_titles_grow_with_rows(self):
        rows = [row(i) for i in range(1, 41)]
        table = streamlit_app.render_table(rows)
        self.assertEqual(table.count('target="_blank"'), 40)
        self.assertIn('data-sort="1">1</td>', table)
        self.assertIn('data-sort="40">40</td>', table)
        self.assertIn('href="https://openalex.org/W40"', table)
        self.assertIn('>Work 40</a>', table)
        for column in range(len(streamlit_app.TABLE_COLUMNS)):
            self.assertIn(f'data-column="{column}"', table)

    def test_heading_dropdowns_include_values_and_unclassified(self):
        first = row(1)
        first.update(type="book-review", topic="Music History and Culture", subfield="Music",
                     field="Arts and Humanities", domain="Social Sciences")
        second = row(2)
        table = streamlit_app.render_table([first, second])
        for label in ("Type", "Topic", "Subfield", "Field", "Domain"):
            self.assertIn(f'aria-label="Filter {label}"', table)
        self.assertEqual(table.count('class="filter-select"'), 5)
        self.assertIn('>Music History and Culture</option>', table)
        self.assertIn('>Unclassified</option>', table)
        self.assertIn("row.cells[column].dataset.sort !== value", table)
        self.assertIn("Showing ${visible} of ${body.rows.length} publications", table)

    def test_filter_options_escape_openalex_text(self):
        suspicious = row(1)
        suspicious["topic"] = '<img src=x onerror="alert(1)">'
        table = streamlit_app.render_table([suspicious])
        self.assertNotIn('<img src=x', table)
        self.assertIn('&lt;img src=x onerror=', table)

    def test_title_link_escapes_untrusted_text_and_url(self):
        suspicious = row(1)
        suspicious["title"] = '<img src=x onerror="alert(1)">'
        suspicious["openalex_url"] = 'javascript:alert(1)'
        table = streamlit_app.render_table([suspicious])
        self.assertNotIn('<img src=x', table)
        self.assertNotIn('href="javascript:', table)
        self.assertIn('href="https://openalex.org/W1"', table)
        self.assertIn('&lt;img src=x onerror=', table)

    def test_session_starts_from_seed_and_click_updates_table_and_download(self):
        st = self.fake_streamlit([False, True])
        new_rows = [row(i, "2026-10-14") for i in range(21, 41)]
        with patch.dict(sys.modules, {"streamlit": st}), \
             patch.object(streamlit_app, "next_older_rows", return_value=new_rows):
            with self.assertRaises(RerunRequested):
                streamlit_app.main()
            streamlit_app.main()
            streamlit_app.main()
        self.assertEqual(st.metric.call_args_list[0].args, ("Total publications", 20))
        self.assertEqual(st.metric.call_args_list[1].args, ("Total publications", 40))
        self.assertEqual(len(st.session_state["publications"]), 40)
        self.assertIn('data-sort="40">40</td>', st.iframe.call_args.args[0])
        download = st.download_button.call_args.kwargs["data"]
        self.assertEqual(len(list(csv.DictReader(io.StringIO(download.decode("utf-8-sig"))))), 40)

    def test_session_keeps_rows_on_fetch_error(self):
        st = self.fake_streamlit([True])
        with patch.dict(sys.modules, {"streamlit": st}), \
             patch.object(streamlit_app, "next_older_rows", side_effect=RuntimeError("offline")):
            with self.assertRaises(RerunRequested):
                streamlit_app.main()
            streamlit_app.main()
        self.assertEqual(len(st.session_state["publications"]), 20)
        st.error.assert_called_once()
        self.assertEqual(st.metric.call_args.args, ("Total publications", 20))

    def test_existing_session_renders_and_exports_seed_classifications(self):
        st = self.fake_streamlit([False])
        seed = streamlit_app.read_seed_rows()
        st.session_state["publications"] = [
            {key: value for key, value in item.items() if key not in collector.TOPIC_HEADERS}
            for item in seed
        ] + [row(999, "2026-10-14")]
        with patch.dict(sys.modules, {"streamlit": st}):
            streamlit_app.main()
        self.assertEqual(len(st.session_state["publications"]), 21)
        self.assertEqual(st.session_state["publications"][0]["subfield"], "Music")
        self.assertIn("Music History and Culture", st.iframe.call_args.args[0])
        downloaded = list(csv.DictReader(io.StringIO(
            st.download_button.call_args.kwargs["data"].decode("utf-8-sig"))))
        self.assertEqual(downloaded[0]["field"], "Arts and Humanities")
        self.assertEqual(downloaded[-1]["openalex_id"], "W999")

    def test_reload_restores_60_from_same_browser(self):
        seed = streamlit_app.read_seed_rows()
        saved = [row(i, "2026-10-14") for i in range(100, 140)]
        st = self.fake_streamlit([False])
        st.components.v2.component.return_value.return_value.snapshot = {
            "status": "ready", "payload": {"version": 1, "added": saved},
        }
        with patch.dict(sys.modules, {"streamlit": st}):
            with self.assertRaises(RerunRequested):
                streamlit_app.main()
            streamlit_app.main()
        self.assertEqual(len(st.session_state["publications"]), 60)
        self.assertEqual(st.metric.call_args.args, ("Total publications", 60))
        saved_again = st.components.v2.component.return_value.call_args.kwargs["data"]
        self.assertEqual(saved_again["mode"], "save")
        self.assertEqual(len(saved_again["added"]), 40)
        self.assertEqual(len(streamlit_app.added_rows(st.session_state["publications"], seed)), 40)

    def test_each_click_saves_the_new_batch(self):
        st = self.fake_streamlit([True, True])
        st.session_state["publications"] = streamlit_app.read_seed_rows()
        batches = [[row(i, "2026-10-14") for i in range(100, 120)],
                   [row(i, "2026-10-13") for i in range(120, 140)]]
        with patch.dict(sys.modules, {"streamlit": st}), \
             patch.object(streamlit_app, "next_older_rows", side_effect=batches):
            streamlit_app.main()
            streamlit_app.main()
        save_calls = st.components.v2.component.return_value.call_args_list
        self.assertEqual([len(call.kwargs["data"]["added"]) for call in save_calls], [20, 40])
        self.assertEqual(len(st.session_state["publications"]), 60)

    def test_waits_for_browser_snapshot_before_initializing(self):
        st = self.fake_streamlit([])
        st.components.v2.component.return_value.return_value.snapshot = None
        with patch.dict(sys.modules, {"streamlit": st}):
            with self.assertRaises(StopRequested):
                streamlit_app.main()
        self.assertNotIn("publications", st.session_state)
        st.button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
