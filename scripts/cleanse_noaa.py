"""Shortcut: python scripts/cleanse_noaa.py  (same as: python fishmarket_pipeline.py --no-api)"""
import subprocess, sys, pathlib
root = pathlib.Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.call([sys.executable, str(root / "fishmarket_pipeline.py"), "--no-api", *sys.argv[1:]]))
