"""Streamlit interface for browsing older Lehigh publications from OpenAlex."""

import csv
import html
import io
import re
from datetime import date
from pathlib import Path

import collector


SEED_CSV = Path(__file__).resolve().parent / "publications.csv"
BATCH_SIZE = 20
PAGE_SIZE = 100
MAX_PAGES = 100
TABLE_COLUMNS = (
    ("#", None),
    ("Title", "title"),
    ("Date", "publication_date"),
    ("Authors", "authors"),
    ("Source", "source"),
    ("Type", "type"),
    ("Topic", "topic"),
    ("Subfield", "subfield"),
    ("Field", "field"),
    ("Domain", "domain"),
    ("DOI", "doi"),
    ("OpenAlex ID", "openalex_id"),
)
FILTERABLE_KEYS = {"type", "topic", "subfield", "field", "domain"}
BROWSER_STORAGE_JS = """
const STORAGE_KEY = 'openalex-simple-poc:publications:v1';
export default function({data, setStateValue}) {
  try {
    if (data.mode === 'load') {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      setStateValue('snapshot', {
        status: 'ready',
        payload: saved === null ? null : JSON.parse(saved)
      });
    } else if (data.mode === 'save') {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 1,
        added: data.added
      }));
    }
  } catch (error) {
    setStateValue('snapshot', {status: 'unavailable'});
  }
}
"""


def read_seed_rows(path=SEED_CSV):
    """Read the bundled sample without modifying it."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != list(collector.HEADERS):
            raise ValueError(f"Unexpected CSV columns in {path.name}")
        rows = list(reader)
    if not rows or not any(row["publication_date"] for row in rows):
        raise ValueError(f"{path.name} has no dated publications")
    return rows


def fill_seed_classifications(rows, seed_rows):
    """Fill missing topic fields in sessions started before the seed was enriched."""
    by_id = {row["openalex_id"].strip().lower(): row for row in seed_rows}
    updated = []
    for row in rows:
        seed = by_id.get((row.get("openalex_id") or "").strip().lower())
        if not seed:
            updated.append(row)
            continue
        missing = {key: seed[key] for key in collector.TOPIC_HEADERS if not row.get(key)}
        updated.append({**row, **missing} if missing else row)
    return updated


def added_rows(rows, seed_rows):
    """Store only fetched works so bundled seed updates remain authoritative."""
    seed_ids = {row["openalex_id"].strip().lower() for row in seed_rows}
    return [row for row in rows if row["openalex_id"].strip().lower() not in seed_ids]


def restore_browser_rows(seed_rows, payload):
    """Restore valid saved works after the bundled 20, skipping duplicates."""
    rows = list(seed_rows)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return rows
    saved = payload.get("added")
    if not isinstance(saved, list):
        return rows
    seen_ids = {row["openalex_id"].strip().lower() for row in rows}
    seen_dois = {collector.normalize_doi(row["doi"]) for row in rows if row["doi"]}
    for item in saved:
        if not isinstance(item, dict):
            continue
        row = {key: item.get(key) if isinstance(item.get(key), str) else ""
               for key in collector.HEADERS}
        work_id = row["openalex_id"].strip().upper()
        try:
            date.fromisoformat(row["publication_date"])
        except ValueError:
            continue
        if not re.fullmatch(r"W\d+", work_id):
            continue
        doi = collector.normalize_doi(row["doi"])
        if work_id.lower() in seen_ids or (doi and doi in seen_dois):
            continue
        row["openalex_id"] = work_id
        row["doi"] = doi
        row["openalex_url"] = f"https://openalex.org/{work_id}"
        seen_ids.add(work_id.lower())
        if doi:
            seen_dois.add(doi)
        rows.append(row)
    return rows


def next_older_rows(rows, batch_size=BATCH_SIZE):
    """Find up to batch_size unseen works on or before the oldest saved date.

    Return only new rows so callers can commit the batch after all requests succeed.
    """
    if not 1 <= batch_size <= PAGE_SIZE:
        raise ValueError("batch_size must be between 1 and 100")
    dated = [row["publication_date"] for row in rows if row["publication_date"]]
    if not dated:
        raise ValueError("No dated publications are available")
    cutoff = min(dated)
    seen_ids = {row["openalex_id"].rsplit("/", 1)[-1].strip().lower() for row in rows}
    seen_dois = {collector.normalize_doi(row["doi"]) for row in rows if row["doi"]}
    added = []

    # OpenAlex basic paging covers the first 10,000 results (100 pages of 100).
    for page in range(1, MAX_PAGES + 1):
        works = collector.fetch_page(None, cutoff, page, page_size=PAGE_SIZE)
        for work in works:
            row = collector.to_row(work)
            work_id = row["openalex_id"].strip().lower()
            doi = collector.normalize_doi(row["doi"])
            if not work_id or not row["publication_date"] or row["publication_date"] > cutoff:
                continue
            if work_id in seen_ids or (doi and doi in seen_dois):
                continue
            seen_ids.add(work_id)
            if doi:
                seen_dois.add(doi)
            added.append(row)
            if len(added) == batch_size:
                return added
        if len(works) < PAGE_SIZE:
            break
    return added


def csv_bytes(rows):
    """Build a download in memory, with the collector's column order."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=collector.HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def openalex_link(row):
    """Use only an OpenAlex work URL for a title link."""
    url = row.get("openalex_url") or ""
    if re.fullmatch(r"https://openalex\.org/W\d+/?", url, re.IGNORECASE):
        return url
    work_id = (row.get("openalex_id") or "").strip()
    if re.fullmatch(r"W\d+", work_id, re.IGNORECASE):
        return f"https://openalex.org/{work_id.upper()}"
    return ""


def render_table(rows):
    """Render a linked table with sorting and heading dropdown filters."""
    headers = []
    for index, (label, key) in enumerate(TABLE_COLUMNS):
        escaped_label = html.escape(label)
        sort_button = (
            f'<button class="sort-button" type="button" data-column="{index}" '
            f'aria-label="Sort by {escaped_label}" title="Sort by {escaped_label}">'
            f'<span aria-hidden="true">{"↑" if index == 0 else "↕"}</span></button>'
        )
        if key in FILTERABLE_KEYS:
            values = sorted({str(row.get(key) or "") for row in rows}, key=str.casefold)
            options = ['<option value="all">All values</option>']
            options.extend(
                f'<option value="{number}" data-value="{html.escape(value, quote=True)}">'
                f'{html.escape(value or "Unclassified")}</option>'
                for number, value in enumerate(values)
            )
            heading = (
                f'<button class="filter-trigger" type="button" data-column="{index}" '
                f'aria-label="Filter {escaped_label}" aria-expanded="false">'
                f'{escaped_label} <span aria-hidden="true">▾</span></button>'
                f'<select class="filter-select" data-column="{index}" '
                f'aria-label="Filter {escaped_label}" hidden>{"".join(options)}</select>'
            )
        else:
            heading = f'<span class="plain-label">{escaped_label}</span>'
        headers.append(
            f'<th scope="col" aria-sort="{"ascending" if index == 0 else "none"}">'
            f'<div class="header-control">{heading}{sort_button}</div></th>'
        )
    headers = "".join(headers)
    table_rows = []
    for number, row in enumerate(rows, start=1):
        cells = []
        for index, (_, key) in enumerate(TABLE_COLUMNS):
            value = str(number) if key is None else str(row.get(key) or "")
            display = html.escape(value)
            if index == 1:
                url = openalex_link(row)
                if url:
                    display = (
                        f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                        f'rel="noopener noreferrer">{display}</a>'
                    )
            cells.append(f'<td data-sort="{html.escape(value, quote=True)}">{display}</td>')
        table_rows.append("<tr>" + "".join(cells) + "</tr>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #fff; color: #182230; font: 14px/1.4 system-ui, sans-serif; }}
.table-tools {{ display: flex; align-items: center; gap: 12px; padding: 0 2px 9px; color: #475467; font-size: 13px; }}
.clear-filters {{ border: 0; background: none; color: #175cd3; font: inherit; font-weight: 600; cursor: pointer; }}
.table-wrap {{ height: 575px; overflow: auto; background: #fff; border: 1px solid #d0d5dd; border-radius: 8px; }}
table {{ width: 100%; min-width: 2520px; table-layout: fixed; border-collapse: collapse; background: #fff; }}
th {{ position: sticky; top: 0; z-index: 1; background: #f1f5f9; color: #253047; text-align: left; border-bottom: 1px solid #cbd5e1; }}
.header-control {{ display: flex; align-items: center; min-height: 43px; flex-wrap: wrap; }}
.plain-label {{ padding: 9px 0 9px 12px; font-weight: 650; }}
th button {{ padding: 9px 5px; border: 0; background: none; color: inherit; font: inherit; font-weight: 650; text-align: left; cursor: pointer; white-space: nowrap; }}
th .filter-trigger {{ padding-left: 12px; }}
th .filter-trigger.active {{ color: #175cd3; }}
th .sort-button {{ margin-left: auto; padding: 9px 12px; font-size: 16px; }}
th select {{ width: calc(100% - 16px); margin: 0 8px 8px; padding: 6px; border: 1px solid #98a2b3; border-radius: 5px; background: #fff; color: #182230; font: inherit; }}
th button:hover {{ background: #e6eef8; }}
th button:focus-visible, th select:focus-visible {{ outline: 2px solid #175cd3; outline-offset: -3px; }}
td {{ padding: 11px 12px; background: #fff; color: #253047; border-bottom: 1px solid #e4e8ee; vertical-align: top; overflow-wrap: anywhere; }}
tbody tr:nth-child(even) td {{ background: #f8fafc; }}
tbody tr:hover td {{ background: #edf5ff; }}
th:nth-child(1), td:nth-child(1) {{ width: 55px; font-variant-numeric: tabular-nums; }}
th:nth-child(2), td:nth-child(2) {{ width: 430px; }}
th:nth-child(3), td:nth-child(3) {{ width: 115px; white-space: nowrap; font-variant-numeric: tabular-nums; }}
th:nth-child(4), td:nth-child(4) {{ width: 285px; }}
th:nth-child(5), td:nth-child(5) {{ width: 210px; }}
th:nth-child(6), td:nth-child(6) {{ width: 120px; }}
th:nth-child(7), td:nth-child(7) {{ width: 245px; }}
th:nth-child(8), td:nth-child(8) {{ width: 175px; }}
th:nth-child(9), td:nth-child(9) {{ width: 185px; }}
th:nth-child(10), td:nth-child(10) {{ width: 165px; }}
th:nth-child(11), td:nth-child(11) {{ width: 215px; }}
th:nth-child(12), td:nth-child(12) {{ width: 150px; white-space: nowrap; }}
a {{ color: #175cd3; text-decoration: underline; text-underline-offset: 2px; }}
a:visited {{ color: #6941c6; }}
a:hover {{ color: #0b4ab8; }}
</style></head><body>
<div class="table-tools"><span id="visible-count">Showing {len(rows)} of {len(rows)} publications</span><button class="clear-filters" type="button" hidden>Clear filters</button></div>
<div class="table-wrap"><table aria-label="Publications">
<thead><tr>{headers}</tr></thead><tbody>{''.join(table_rows)}</tbody>
</table></div>
<script>
const table = document.querySelector('table');
const body = table.tBodies[0];
const buttons = [...table.querySelectorAll('.sort-button')];
const collator = new Intl.Collator(undefined, {{numeric: true, sensitivity: 'base'}});
let activeColumn = 0;
let ascending = true;
const filters = new Map();
const visibleCount = document.querySelector('#visible-count');
const clearFilters = document.querySelector('.clear-filters');
function applyFilters() {{
  let visible = 0;
  for (const row of body.rows) {{
    row.hidden = [...filters].some(([column, value]) => row.cells[column].dataset.sort !== value);
    if (!row.hidden) visible++;
  }}
  visibleCount.textContent = `Showing ${{visible}} of ${{body.rows.length}} publications`;
  clearFilters.hidden = filters.size === 0;
}}
for (const trigger of table.querySelectorAll('.filter-trigger')) {{
  trigger.addEventListener('click', () => {{
    const select = trigger.parentElement.querySelector('.filter-select');
    select.hidden = !select.hidden;
    trigger.setAttribute('aria-expanded', String(!select.hidden));
    if (!select.hidden) select.focus();
  }});
}}
for (const select of table.querySelectorAll('.filter-select')) {{
  select.addEventListener('change', () => {{
    const column = Number(select.dataset.column);
    if (select.value === 'all') filters.delete(column);
    else filters.set(column, select.selectedOptions[0].dataset.value);
    select.parentElement.querySelector('.filter-trigger').classList.toggle('active', select.value !== 'all');
    applyFilters();
  }});
}}
clearFilters.addEventListener('click', () => {{
  for (const select of table.querySelectorAll('.filter-select')) {{
    select.value = 'all';
    select.parentElement.querySelector('.filter-trigger').classList.remove('active');
  }}
  filters.clear();
  applyFilters();
}});
for (const button of buttons) {{
  button.addEventListener('click', () => {{
    const column = Number(button.dataset.column);
    ascending = column === activeColumn ? !ascending : column !== 2;
    activeColumn = column;
    const sorted = [...body.rows].sort((left, right) => {{
      const a = left.cells[column].dataset.sort;
      const b = right.cells[column].dataset.sort;
      let comparison = column === 0 ? Number(a) - Number(b) :
                       column === 2 ? a.localeCompare(b) : collator.compare(a, b);
      if (!ascending) comparison = -comparison;
      return comparison || Number(left.cells[0].dataset.sort) - Number(right.cells[0].dataset.sort);
    }});
    body.replaceChildren(...sorted);
    for (const header of table.tHead.rows[0].cells) {{
      const selected = Number(header.querySelector('.sort-button').dataset.column) === column;
      header.setAttribute('aria-sort', selected ? (ascending ? 'ascending' : 'descending') : 'none');
      header.querySelector('.sort-button span').textContent = selected ? (ascending ? '↑' : '↓') : '↕';
    }}
  }});
}}
</script></body></html>"""


def main():
    import streamlit as st

    st.set_page_config(page_title="Lehigh research discovery", layout="wide")
    st.title("Lehigh research discovery")
    st.caption("Public OpenAlex works affiliated with Lehigh University")

    try:
        seed_rows = read_seed_rows()
    except (OSError, ValueError) as exc:
        st.error(f"Could not load the bundled publications: {exc}")
        st.stop()
    browser_storage = st.components.v2.component(
        "openalex_browser_publications", js=BROWSER_STORAGE_JS
    )
    if "publications" not in st.session_state:
        result = browser_storage(
            data={"mode": "load"}, key="browser_publications",
            on_snapshot_change=lambda: None,
        )
        snapshot = result.snapshot
        if snapshot is None:
            st.info("Restoring publications saved in this browser...")
            st.stop()
        if isinstance(snapshot, dict) and snapshot.get("status") == "ready":
            st.session_state["publications"] = restore_browser_rows(
                seed_rows, snapshot.get("payload")
            )
        else:
            st.session_state["publications"] = seed_rows
            st.session_state["browser_storage_unavailable"] = True
        st.rerun()
    else:
        st.session_state["publications"] = fill_seed_classifications(
            st.session_state["publications"], seed_rows
        )

    if st.button("Get next 20 older publications"):
        try:
            with st.spinner("Fetching older publications..."):
                added = next_older_rows(st.session_state["publications"])
        except (RuntimeError, ValueError, OSError) as exc:
            st.error(f"Could not fetch more publications: {exc}")
        else:
            if added:
                st.session_state["publications"] = st.session_state["publications"] + added
                st.success(f"Added {len(added)} older publications.")
            else:
                st.info("No more unseen publications were found.")

    rows = st.session_state["publications"]
    result = browser_storage(
        data={"mode": "save", "added": added_rows(rows, seed_rows)},
        key="browser_publications", on_snapshot_change=lambda: None,
    )
    if (st.session_state.get("browser_storage_unavailable") or
            isinstance(result.snapshot, dict) and
            result.snapshot.get("status") == "unavailable"):
        st.warning("This browser is blocking saved publications. Download the CSV to keep your list.")
    st.metric("Total publications", len(rows))
    st.download_button(
        "Download CSV",
        data=csv_bytes(rows),
        file_name="lehigh_publications.csv",
        mime="text/csv",
    )
    st.iframe(
        render_table(rows), height=630, width="stretch",
        alt="Sortable table of Lehigh publications",
    )


if __name__ == "__main__":
    main()
