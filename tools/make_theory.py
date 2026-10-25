"""Builds engine/data/theory.json (the opening theory tree) from openings.tsv, so the app
doesn't spend 20 s building it on first use. Run after updating openings.tsv."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))
os.environ.setdefault("CHESS_REVIEW_DATA", tempfile.mkdtemp())
import theory
t = theory.tree()
out = os.path.join(HERE, "..", "engine", "data", "theory.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(t, f, separators=(",", ":"))
print(out, os.path.getsize(out))
