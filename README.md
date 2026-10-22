# Lehigh Research Discovery

A Streamlit prototype for exploring scholarly works associated with Lehigh University in [OpenAlex](https://openalex.org/). It offers a simple way to browse publication metadata, move backward through older records, and export a collection for further review.

**Live demo:** [Open the research discovery app](https://openalex-simple-poc-mdr6cd3sshezxcsnhs7xvv.streamlit.app/)

## What the app does

The app starts with 20 bundled publications. From there, a visitor can:

- Click **Get next 20 older publications** to add up to 20 works from OpenAlex.
- Sort the table by any column and filter by work type, topic, subfield, field, or domain.
- Open a publication's OpenAlex record by clicking its title.
- Download all collected records as a CSV file for review in Excel or another spreadsheet tool.

Added publications are saved in the visitor's browser, so the collection remains available after a reload or a return visit in the same browser. Each browser has its own collection; the app does not store visitors' lists on the server. The CSV download is a portable copy that can be shared separately.

## Data and selection method

The bundled `publications.csv` supplies the initial 20 records. For subsequent batches, the app queries the public [OpenAlex Works API](https://help.openalex.org/api/) for works that OpenAlex associates with Lehigh University (`I186143895`). Results are requested in descending publication-date order, dated **on or before the oldest date already saved**. Including that date prevents works published on the same day from being skipped.

The app checks each candidate against the saved OpenAlex IDs and normalized DOIs, skips matches, and adds up to 20 unseen works. Topic, subfield, field, and domain come from OpenAlex's `primary_topic` classification. These labels are automatically assigned, and the collection may include articles, reviews, datasets, and other work types. The prototype is intended for discovery and review, not as a vetted list of research opportunities.

## Run locally

With Python 3.10 or newer installed, run:

```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

Fetching new records requires an internet connection. The original local demonstration is also available with `python3 demo.py --open`; it stores its growing list in a separate `demo_publications.csv` file.

## Tests and deployment

Run the test suite with:

```bash
python3 -m unittest discover -v
```

To deploy a copy on [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), select this repository and its `main` branch, then set `streamlit_app.py` as the entrypoint. The repository includes the seed CSV and `requirements.txt` needed to launch the app.
