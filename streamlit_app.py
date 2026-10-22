"""Streamlit interface for browsing older Lehigh publications from OpenAlex."""

import csv
import html
import io
import re
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
    ("DOI", "doi"),
    ("OpenAlex ID", "openalex_id"),
)


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
    """Render a sortable, linked table without changing the saved CSV rows."""
    headers = "".join(
        f'<th scope="col" aria-sort="{"ascending" if index == 0 else "none"}">'
        f'<button type="button" data-column="{index}" aria-label="Sort by {html.escape(label)}">'
        f'{html.escape(label)} <span aria-hidden="true">{"↑" if index == 0 else "↕"}</span>'
        "</button></th>"
        for index, (label, _) in enumerate(TABLE_COLUMNS)
    )
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
.table-wrap {{ height: 610px; overflow: auto; background: #fff; border: 1px solid #d0d5dd; border-radius: 8px; }}
table {{ width: 100%; min-width: 1580px; table-layout: fixed; border-collapse: collapse; background: #fff; }}
th {{ position: sticky; top: 0; z-index: 1; background: #f1f5f9; color: #253047; text-align: left; border-bottom: 1px solid #cbd5e1; }}
th button {{ width: 100%; padding: 12px; border: 0; background: none; color: inherit; font: inherit; font-weight: 650; text-align: left; cursor: pointer; white-space: nowrap; }}
th button:hover {{ background: #e6eef8; }}
th button:focus-visible {{ outline: 2px solid #175cd3; outline-offset: -3px; }}
td {{ padding: 11px 12px; background: #fff; color: #253047; border-bottom: 1px solid #e4e8ee; vertical-align: top; overflow-wrap: anywhere; }}
tbody tr:nth-child(even) td {{ background: #f8fafc; }}
tbody tr:hover td {{ background: #edf5ff; }}
th:nth-child(1), td:nth-child(1) {{ width: 55px; font-variant-numeric: tabular-nums; }}
th:nth-child(2), td:nth-child(2) {{ width: 430px; }}
th:nth-child(3), td:nth-child(3) {{ width: 115px; white-space: nowrap; font-variant-numeric: tabular-nums; }}
th:nth-child(4), td:nth-child(4) {{ width: 285px; }}
th:nth-child(5), td:nth-child(5) {{ width: 210px; }}
th:nth-child(6), td:nth-child(6) {{ width: 120px; }}
th:nth-child(7), td:nth-child(7) {{ width: 215px; }}
th:nth-child(8), td:nth-child(8) {{ width: 150px; white-space: nowrap; }}
a {{ color: #175cd3; text-decoration: underline; text-underline-offset: 2px; }}
a:visited {{ color: #6941c6; }}
a:hover {{ color: #0b4ab8; }}
</style></head><body>
<div class="table-wrap"><table aria-label="Publications">
<thead><tr>{headers}</tr></thead><tbody>{''.join(table_rows)}</tbody>
</table></div>
<script>
const table = document.querySelector('table');
const body = table.tBodies[0];
const buttons = [...table.querySelectorAll('th button')];
const collator = new Intl.Collator(undefined, {{numeric: true, sensitivity: 'base'}});
let activeColumn = 0;
let ascending = true;
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
      const selected = Number(header.querySelector('button').dataset.column) === column;
      header.setAttribute('aria-sort', selected ? (ascending ? 'ascending' : 'descending') : 'none');
      header.querySelector('span').textContent = selected ? (ascending ? '↑' : '↓') : '↕';
    }}
  }});
}}
</script></body></html>"""


def main():
    import streamlit as st

    st.set_page_config(page_title="Lehigh research discovery", layout="wide")
    st.title("Lehigh research discovery")
    st.caption("Public OpenAlex works affiliated with Lehigh University")

    if "publications" not in st.session_state:
        try:
            st.session_state["publications"] = read_seed_rows()
        except (OSError, ValueError) as exc:
            st.error(f"Could not load the bundled publications: {exc}")
            st.stop()

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
