"""Preserve diagnostics from the real, disposable Homebrew capture test."""
import json
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parent
with (root / "validation/real-capture-smoke.log").open("w") as output:
    result = subprocess.run([sys.executable, "real_brew_smoke.py", "--capture-only"],
                            cwd=root, stdout=output, stderr=subprocess.STDOUT)
print(json.dumps({"exit_code": result.returncode, "log": "validation/real-capture-smoke.log"}))
if result.returncode:
    print((root / "validation/real-capture-smoke.log").read_text()[-10000:])
sys.exit(result.returncode)
