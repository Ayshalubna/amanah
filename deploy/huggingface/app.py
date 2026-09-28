"""Hugging Face Space entry point (free CPU tier, Gradio SDK slot).

Fetches Amanah from GitHub, builds the synthetic data, risk model and caches once,
then serves the FastAPI web app on port 7860. Gradio itself is not used.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/Ayshalubna/amanah.git"
SRC = Path.home() / "amanah-src"

os.environ.setdefault("AMANAH_LLM", "none")
os.environ.setdefault("AMANAH_EMBEDDINGS", "off")
os.environ.setdefault("AMANAH_DB", "/tmp/amanah.db")

if not (SRC / "amanah").exists():
    subprocess.run(["git", "clone", "--depth", "1", REPO, str(SRC)], check=True)

os.chdir(SRC)
sys.path.insert(0, str(SRC))

if not (SRC / "artifacts" / "screening_cache.json").exists():
    subprocess.run([sys.executable, "-m", "scripts.train_model"], check=True)
    subprocess.run([sys.executable, "-c",
                    "from amanah import graph, overview; graph.ctx(); overview.screening_all()"], check=True)

import uvicorn  # noqa: E402

from amanah.api import api  # noqa: E402

uvicorn.run(api, host="0.0.0.0", port=int(os.getenv("PORT", "7860")),
            proxy_headers=True, forwarded_allow_ips="*", timeout_keep_alive=30)
