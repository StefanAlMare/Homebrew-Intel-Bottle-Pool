"""Read one installed Node receipt; classify a disposable copy without Brew writes."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pool.imports import BottleImporter

root = Path(__file__).resolve().parent
receipt_path = Path("/usr/local/Cellar/node/26.11.0/INSTALL_RECEIPT.json")
if not receipt_path.is_file():
    raise SystemExit("Node 26.11.0 receipt is not installed on this Mac; use the isolated regression fixture instead")
receipt = json.loads(receipt_path.read_text())
with tempfile.TemporaryDirectory(prefix="pool-node-receipt-") as temporary:
    state = Path(temporary)
    cache = state / "empty-cache"
    cache.mkdir()
    info = {"full_name": "node", "installed": [dict(receipt, version="26.11.0")]}
    brew = SimpleNamespace(cache=cache, run=lambda *args: json.dumps({"formulae": [info]}))
    client = SimpleNamespace(state=state, config={})
    report = BottleImporter(client, brew).scan()
    candidate = report["candidates"][0]
    assert candidate["classification"] == "local_source_no_bottle", candidate
    result = {"formula": "node", "version": "26.11.0", "arch": receipt.get("arch"),
              "built_as_bottle": receipt.get("built_as_bottle"),
              "poured_from_bottle": receipt.get("poured_from_bottle"),
              "classification": candidate["classification"],
              "scope": "read-only installed receipt, isolated scanner state; no Brew commands"}
    (root / "validation").mkdir(exist_ok=True)
    (root / "validation/node-installed-receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
