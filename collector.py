"""Collect a small, local CSV of recent Lehigh University publications.

Run: python3 collector.py
No third-party Python packages or university credentials are required.
"""

import argparse
import csv
import json
import ssl
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.openalex.org/works"
LEHIGH_ID = "I186143895"
LEGACY_HEADERS = ("openalex_id", "title", "publication_date", "doi", "authors", "source", "type", "openalex_url")
TOPIC_HEADERS = ("topic", "subfield", "field", "domain")
HEADERS = LEGACY_HEADERS + TOPIC_HEADERS


def normalize_doi(value):
    """Turn DOI URLs and plain DOI strings into one comparable key."""
    if not value:
        return ""
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.strip()


def unique_works(works, limit=20):
    """Keep the first (newest) work for each DOI, or OpenAlex ID if DOI is absent."""
    seen = set()
    result = []
    for work in works:
        doi = normalize_doi(work.get("doi"))
        openalex_id = (work.get("id") or "").strip().lower()
        key = ("doi", doi) if doi else ("openalex", openalex_id)
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(work)
        if len(result) == limit:
            break
    return result


def to_row(work):
    authors = [entry.get("author", {}).get("display_name", "") for entry in work.get("authorships") or []]
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    topic = work.get("primary_topic") or {}
    return {
        "openalex_id": (work.get("id") or "").rsplit("/", 1)[-1],
        "title": work.get("title") or "",
        "publication_date": work.get("publication_date") or "",
        "doi": normalize_doi(work.get("doi")),
        "authors": "; ".join(name for name in authors if name),
        "source": source.get("display_name") or "",
        "type": work.get("type") or "",
        "openalex_url": work.get("id") or "",
        "topic": topic.get("display_name") or "",
        "subfield": (topic.get("subfield") or {}).get("display_name") or "",
        "field": (topic.get("field") or {}).get("display_name") or "",
        "domain": (topic.get("domain") or {}).get("display_name") or "",
    }


def fetch_page(since, until, page, page_size=50):
    filters = [f"authorships.institutions.id:{LEHIGH_ID}"]
    if since:
        filters.append(f"from_publication_date:{since}")
    if until:
        filters.append(f"to_publication_date:{until}")
    params = {
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per_page": page_size,
        "page": page,
        "select": "id,doi,title,publication_date,type,authorships,primary_location,primary_topic",
    }
    request = Request(f"{API_URL}?{urlencode(params)}", headers={"User-Agent": "lehigh-venture-studio-poc/0.1"})
    # The python.org macOS installer sometimes lacks its CA bundle; use the
    # macOS system bundle when present. Certificate verification stays on.
    system_ca = Path("/etc/ssl/cert.pem")
    cafile = str(system_ca) if not ssl.get_default_verify_paths().cafile and system_ca.exists() else None
    tls_context = ssl.create_default_context(cafile=cafile)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20, context=tls_context) as response:
                return json.load(response).get("results", [])
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"OpenAlex returned HTTP {exc.code}. Try again later or check the API URL.") from exc
        except URLError as exc:
            if attempt == 2:
                raise RuntimeError(f"Could not reach OpenAlex: {exc.reason}") from exc
        time.sleep(2 ** attempt)
    return []


def collect(limit=20, since=None, until=None):
    until = until or date.today()
    since = since or (until - timedelta(days=365))
    if since > until:
        raise ValueError("--since must be on or before --until")
    gathered = []
    for page in range(1, 6):
        batch = fetch_page(since.isoformat(), until.isoformat(), page)
        gathered.extend(batch)
        found = unique_works(gathered, limit)
        if len(found) >= limit or len(batch) < 50:
            return found
    return unique_works(gathered, limit)


def write_csv(works, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(to_row(work) for work in works)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="number of unique publications (default: 20)")
    parser.add_argument("--since", type=date.fromisoformat, help="earliest publication date, YYYY-MM-DD (default: past year)")
    parser.add_argument("--until", type=date.fromisoformat, help="latest publication date, YYYY-MM-DD (default: today)")
    parser.add_argument("--output", type=Path, default=Path("publications.csv"), help="local CSV path")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    works = collect(args.limit, args.since, args.until)
    write_csv(works, args.output)
    print(f"Saved {len(works)} unique publications to {args.output}")
    if len(works) < args.limit:
        print("Fewer results were available in the selected date range.")


if __name__ == "__main__":
    main()
