"""Run the isolated local regression suite and retain its exact report."""
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
validation = root / "validation"
validation.mkdir(exist_ok=True)
log = validation / "tests.log"
with log.open("w") as output:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
                            cwd=root, stdout=output, stderr=subprocess.STDOUT)
contents = log.read_text()
count = re.search(r"Ran (\d+) tests in ([\d.]+)s", contents)
report = {"exit_code": result.returncode, "tests": int(count[1]) if count else None,
          "duration_seconds": float(count[2]) if count else None,
          "summary": contents.rstrip().splitlines()[-1], "scope": "local isolated fixtures"}
(validation / "tests.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
if result.returncode:
    print(contents[contents.find("======================================================================"):])
sys.exit(result.returncode)
