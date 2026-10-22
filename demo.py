"""Local, one-button OpenAlex demo. Run: python3 demo.py"""

import argparse
import csv
import html
import os
import shutil
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from collector import HEADERS, fetch_page, normalize_doi, to_row


FOLDER = Path(__file__).resolve().parent
INITIAL_CSV = FOLDER / "publications.csv"
DEMO_CSV = FOLDER / "demo_publications.csv"


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != list(HEADERS):
            raise ValueError(f"Unexpected CSV columns in {path.name}")
        return list(reader)


def ensure_demo_csv(initial=INITIAL_CSV, demo=DEMO_CSV):
    """Seed the demo once; never change the original 20-row CSV."""
    if not demo.exists():
        if not initial.exists():
            raise FileNotFoundError(f"Missing {initial.name}. Run python3 collector.py first.")
        rows = read_rows(initial)
        if not rows:
            raise ValueError(f"{initial.name} has no publications")
        shutil.copyfile(initial, demo)


def save_rows_atomic(path, rows):
    """Replace the CSV only after the complete new version has been written."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", dir=path.parent, prefix=".demo-", suffix=".csv", delete=False) as file:
        temp_path = Path(file.name)
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def add_next_batch(path=DEMO_CSV, batch_size=20):
    """Add the next 20 unseen works dated on or before our oldest saved date."""
    rows = read_rows(path)
    if not rows:
        raise ValueError("The demo CSV is empty")
    cutoff = min(row["publication_date"] for row in rows if row["publication_date"])
    seen_ids = {row["openalex_id"].strip().lower() for row in rows}
    seen_dois = {normalize_doi(row["doi"]) for row in rows if row["doi"]}
    added = []

    # Basic paging supports the first 10,000 results; 100 pages × 100 works.
    for page in range(1, 101):
        works = fetch_page(None, cutoff, page, page_size=100)
        for work in works:
            row = to_row(work)
            work_id = row["openalex_id"].strip().lower()
            doi = normalize_doi(row["doi"])
            if not work_id or not row["publication_date"] or row["publication_date"] > cutoff:
                continue
            if work_id in seen_ids or (doi and doi in seen_dois):
                continue
            seen_ids.add(work_id)
            if doi:
                seen_dois.add(doi)
            added.append(row)
            if len(added) == batch_size:
                save_rows_atomic(path, rows + added)
                return added
        if len(works) < 100:
            break

    if added:
        save_rows_atomic(path, rows + added)
    return added


def render_page(rows, added=0, error=""):
    count = len(rows)
    oldest = min((row["publication_date"] for row in rows if row["publication_date"]), default="—")
    newest = max((row["publication_date"] for row in rows if row["publication_date"]), default="—")
    message = f"Added {added} older publications. The CSV now has {count} rows." if added else "Ready to fetch the next 20 older publications."
    if error:
        message = f"Could not fetch more publications: {error}"
    cards = []
    for index, row in enumerate(rows, start=1):
        title = html.escape(row["title"] or "Untitled")
        url = html.escape(row["openalex_url"], quote=True)
        date = html.escape(row["publication_date"])
        authors = html.escape(row["authors"])
        source = html.escape(row["source"])
        work_type = html.escape(row["type"])
        badge = '<span class="badge">New</span>' if added and index > count - added else ""
        cards.append(f'<tr><td>{index}</td><td><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>{badge}</td><td>{date}</td><td>{authors}</td><td>{source}</td><td>{work_type}</td></tr>')
    table = "\n".join(cards)
    status_class = "error" if error else "status"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lehigh research discovery demo</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f5f6f8; color: #17202a; }}
  main {{ max-width: 1200px; margin: auto; padding: 32px 20px 64px; }}
  header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; flex-wrap: wrap; }}
  h1 {{ font-size: 30px; margin: 0 0 8px; }} p {{ line-height: 1.5; }}
  .subtitle {{ color: #53606e; margin: 0; }}
  .controls {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
  button, .download {{ border: 0; border-radius: 9px; padding: 13px 18px; font: inherit; font-weight: 650; cursor: pointer; text-decoration: none; }}
  button {{ background: #6c122b; color: white; }} button:hover {{ background: #4f0d1e; }}
  .download {{ background: white; color: #6c122b; border: 1px solid #c9cdd2; }}
  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; margin: 28px 0 16px; }}
  .stat {{ background: white; border: 1px solid #e1e4e8; border-radius: 10px; padding: 14px 20px; min-width: 135px; }}
  .stat strong {{ display: block; font-size: 23px; }} .stat span {{ color: #5f6b77; font-size: 13px; }}
  .status, .error {{ padding: 12px 16px; border-radius: 8px; margin: 0 0 18px; }}
  .status {{ background: #e9f4ec; color: #20572e; }} .error {{ background: #fff0ef; color: #8a1f18; }}
  .table-wrap {{ overflow-x: auto; background: white; border: 1px solid #e1e4e8; border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }} th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #edf0f2; vertical-align: top; }}
  th {{ background: #fafbfc; position: sticky; top: 0; }} td:nth-child(2) {{ min-width: 300px; }} td:nth-child(4) {{ min-width: 180px; }}
  a {{ color: #6c122b; }} .badge {{ display: inline-block; margin-left: 8px; color: #20572e; background: #e3f2e7; padding: 3px 6px; border-radius: 5px; font-size: 11px; font-weight: bold; }}
  footer {{ color: #66717d; margin-top: 18px; font-size: 13px; }}
</style></head><body><main>
<header><div><h1>Lehigh research discovery</h1><p class="subtitle">A local OpenAlex prototype for Venture Studio</p></div>
<div class="controls"><form method="post" action="/next"><button type="submit" onclick="this.disabled=true; this.textContent='Fetching…'; this.form.submit();">Get next 20 older publications</button></form><a class="download" href="/download">Download CSV</a></div></header>
<div class="stats"><div class="stat"><strong>{count}</strong><span>publications saved</span></div><div class="stat"><strong>{newest}</strong><span>newest date</span></div><div class="stat"><strong>{oldest}</strong><span>oldest date</span></div></div>
<p class="{status_class}">{html.escape(message)}</p>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Publication</th><th>Date</th><th>Authors</th><th>Source</th><th>Type</th></tr></thead><tbody>{table}</tbody></table></div>
<footer>Data: public OpenAlex records affiliated with Lehigh University. Results are not yet screened for Venture Studio relevance. The original 20-row CSV remains unchanged.</footer>
</main></body></html>"""


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/download":
            body = DEMO_CSV.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="lehigh_publications.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route.path != "/":
            self.send_error(404)
            return
        params = parse_qs(route.query)
        added = int(params.get("added", ["0"])[0]) if params.get("added", ["0"])[0].isdigit() else 0
        error = params.get("error", [""])[0]
        body = render_page(read_rows(DEMO_CSV), added=added, error=error).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/next":
            self.send_error(404)
            return
        try:
            count = len(add_next_batch())
            target = f"/?added={count}"
        except (RuntimeError, ValueError, OSError) as exc:
            from urllib.parse import quote
            target = f"/?error={quote(str(exc))}"
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the demo in your default browser")
    args = parser.parse_args()
    ensure_demo_csv()
    address = f"http://127.0.0.1:{args.port}"
    server = HTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"Demo ready: {address}", flush=True)
    print("Press Control-C to stop it.", flush=True)
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
