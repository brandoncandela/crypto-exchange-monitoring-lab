"""Compare regenerated outputs byte-for-byte with tracked files, offline."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = ["README.md", "docs/control-tuning.md", "docs/walkthrough.md",
         "dist/data/lab.json", "dist/data/baseline-proposed.json",
         "dist/data/evaluation-baseline.json", "dist/data/evaluation-proposed.json", "dist/data/metrics.csv"]
before = {p: (ROOT / p).read_bytes() for p in paths}
subprocess.run([sys.executable, str(ROOT / "src/build_lab.py")], check=True, cwd=ROOT)
changed = [p for p in paths if (ROOT / p).read_bytes() != before[p]]
if changed:
    raise SystemExit("Outputs do not reproduce: " + ", ".join(changed))
print("All generated JSON, CSV and documentation reproduce byte-for-byte.")
