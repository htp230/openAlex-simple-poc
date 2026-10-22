# Lehigh OpenAlex research discovery demo

The collector asks the public OpenAlex API for works associated with Lehigh University (`I186143895`), sorts them by publication date, removes repeated DOI or OpenAlex IDs, and writes 20 records to a local CSV. The collector and local demo use only Python's standard library; the deployable app adds Streamlit. None uses a university login or Google Sheets.

## Streamlit app (local or cloud)

Install the app dependency and launch it from this folder:

```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

The app starts each visitor's session with the 20 bundled records in `publications.csv`. It shows the total and a table numbered from 1 through the current count. Click any column heading to sort; click it again to reverse the order. Publication titles link to their OpenAlex pages. **Get next 20 older publications** fetches up to 20 unseen OpenAlex works dated on or before the oldest saved date, excluding matches by either OpenAlex ID or DOI. **Download CSV** exports that session's entire current list. The app does not write results to the server's filesystem. A browser reload or disconnected session can reset the list, so download it before leaving.

To deploy on [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), put `streamlit_app.py`, `collector.py`, `publications.csv`, and `requirements.txt` in the same GitHub repository. In Community Cloud, create an app from that repository and branch, and select `streamlit_app.py` as the entrypoint. The bundled CSV supplies the initial rows; clicking the button needs internet access to OpenAlex. No university account, Google Sheet, or server-side CSV storage is needed.

Run all focused tests, including the Streamlit app's data logic, with:

```bash
python3 -m unittest -v
```

The app data tests use mocked OpenAlex responses, so they do not require a network connection or a running Streamlit server.

## Show the button demo

In the Codex terminal, change into this folder and run:

```bash
python3 demo.py --open
```

Your browser opens `http://127.0.0.1:8765`. It starts with the 20 publications already collected. Click **Get next 20 older publications** to add 20 works on or before the oldest saved date. The page shows the growing count and marks the new rows. Click again to continue backward. **Download CSV** saves the full collection. Stop the server with Control-C in the terminal.

The demo stores its growing list in `demo_publications.csv`. It copies the original `publications.csv` on first launch and leaves that original file alone. If you want to rehearse from the original 20 again, stop the server, delete only `demo_publications.csv`, and restart. It listens on your computer only; an internet connection is needed when you click the fetch button.

For the meeting, start the demo before your professor arrives and leave the page open. The button makes a live OpenAlex request, so allow a few seconds for it to finish. If the network fails, the page shows the error and keeps the existing CSV intact.

## Run it

Open this folder in Codex, then run these commands in its terminal:

```bash
python3 --version
python3 -m unittest -v
python3 collector.py
```

The last command creates `publications.csv` in this folder. Open the CSV with a text editor or spreadsheet program. To choose a different date range:

```bash
python3 collector.py --since 2025-01-01 --until 2026-10-22 --output publications.csv
```

By default, "recent" means the 365 days through the day you run the program. The output includes a title, date, DOI, author names, source, work type, and OpenAlex link. OpenAlex may include book reviews, preprints, or other work types; the CSV is a discovery sample, not a vetted list of commercialization leads.

## Read the code like a Java program

1. `main()` reads command-line options, like a Java `main` method.
2. `collect()` requests pages until it has 20 unique works.
3. `fetch_page()` builds an API URL and turns JSON into Python dictionaries (similar to Java maps).
4. `unique_works()` uses a `set` to remember DOIs; if a DOI is missing, it uses the OpenAlex ID.
5. `to_row()` picks the fields for one spreadsheet row, and `write_csv()` writes them.

`test_collector.py` checks those transformations using small fake records, so the tests do not need an internet connection. The collector itself does need internet access to fetch real publications. If it reports a network or HTTP error, check your connection and try again later. The unauthenticated OpenAlex API has a shared free budget, so a key may eventually be needed for larger work.

`test_demo.py` checks that one click adds 20 unseen records, another click moves backward, and a fetch error does not change the saved CSV.

## A focused two-hour session

- **0–20 min:** Run the tests, then trace one test into `unique_works()`.
- **20–50 min:** Run the collector and inspect three CSV rows against their OpenAlex links.
- **50–80 min:** Change `--since`, rerun, and observe how the results change.
- **80–110 min:** Add one field you want for research discovery, such as `cited_by_count`, and add a test for it.
- **110–120 min:** Write down surprising records and one question for the Venture Studio client about what counts as a useful lead.

Do not connect production university accounts or a shared Google Sheet during this exercise.

## Sources

- OpenAlex API: https://help.openalex.org/api/
- OpenAlex paging: https://help.openalex.org/api/paging/
- Lehigh institution page: https://openalex.org/institutions/I186143895
