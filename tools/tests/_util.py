"""Shared helpers for tools/tests -- import paths + a scratch-copy helper."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for p in (TOOLS, ROOT / "daemon"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def scratch_tree(*rel_paths: str) -> Path:
    """Copy the given repo-relative files/dirs into a fresh temp dir with the
    same layout, so a test can mutate them and point a checker at the copy."""
    dst = Path(tempfile.mkdtemp(prefix="clawdmeter-test-"))
    for rel in rel_paths:
        src = ROOT / rel
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, out)
        else:
            shutil.copy2(src, out)
    return dst
