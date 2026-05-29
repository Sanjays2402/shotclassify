import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Ensure local package srcs are importable even without editable install
for p in ROOT.glob("packages/*/src"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
sys.path.insert(0, str(ROOT / "cli" / "src"))
sys.path.insert(0, str(ROOT))
