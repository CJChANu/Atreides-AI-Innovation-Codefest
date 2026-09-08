#!/usr/bin/env python3
"""Start the web UI and API.

    python run_api.py            # http://127.0.0.1:8000
    python run_api.py --port 9000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n  Ashen Era Archive Investigator → http://{args.host}:{args.port}\n")
    uvicorn.run("src.api.app:app", host=args.host, port=args.port, reload=args.reload)
