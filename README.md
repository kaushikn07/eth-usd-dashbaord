# ETHUSD Quant Dashboard — Streamlit

Live ETH quant research dashboard. Pulls fresh data from Delta Exchange on every page refresh — no cron job, no local server needed.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit frontend |
| `collector.py` | Data fetching + indicator computation |
| `requirements.txt` | Python dependencies |

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud (free)

1. Push all three files (`app.py`, `collector.py`, `requirements.txt`) to a **public GitHub repo**.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app** → select your repo → set **Main file path** to `app.py` → click **Deploy**.
4. Your dashboard will be live at `https://<your-app>.streamlit.app` in ~2 minutes.

## How refresh works

- Every time you load or refresh the page, `collector.py` is called via `build_dataset()`.
- It hits the Delta Exchange public API, computes all indicators, and returns the latest data.
- There is also a **🔄 Refresh Data** button at the top right for manual refresh without a full page reload.
- No `data.json` file is needed — data flows directly from the API into the dashboard.
