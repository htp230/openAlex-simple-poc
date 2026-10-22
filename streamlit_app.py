"""Streamlit interface for browsing older Lehigh publications from OpenAlex."""

import csv
import io
from pathlib import Path

import collector


SEED_CSV = Path(__file__).resolve().parent / "publications.csv"
BATCH_SIZE = 20
PAGE_SIZE = 100
MAX_PAGES = 100


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
    st.dataframe(rows, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
