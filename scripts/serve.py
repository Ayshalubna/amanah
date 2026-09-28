"""Start the Amanah web app and open it in the browser.

Run:  python -m scripts.serve   ->  http://localhost:8000
"""
import threading
import time
import urllib.request
import webbrowser

import uvicorn

URL = "http://localhost:8000"


def _open_when_ready():
    for _ in range(120):
        try:
            urllib.request.urlopen(URL + "/health", timeout=1)
            webbrowser.open(URL)
            return
        except Exception:
            time.sleep(1)


if __name__ == "__main__":
    print("Preparing Amanah (first start takes about 20 seconds)...")
    from amanah import graph, overview

    c = graph.ctx()
    overview.screening_all()
    c.model.explain(c.features.iloc[[0]])  # warm up SHAP so the first investigation is instant
    from amanah.rag import get_retriever

    get_retriever()
    threading.Thread(target=_open_when_ready, daemon=True).start()
    print(f"Amanah is running at {URL}  -  keep this window open, close it to stop.")
    uvicorn.run("amanah.api:api", host="127.0.0.1", port=8000, log_level="warning")
