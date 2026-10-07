"""Read-only production connection check; no live spool or config writes."""
import hashlib
import json
from pathlib import Path
from pool.cli import default_config
from pool.settings import configure_gui


def main():
    path = default_config()
    original = path.read_bytes()
    config = json.loads(original)
    token_path = Path(config["token_file"]).expanduser()
    token_hash = hashlib.sha256(token_path.read_bytes()).hexdigest()
    result = configure_gui(path, {
        "url": config["url"], "token_file": str(token_path),
        "ca_file": config.get("ca_file", ""),
        "allow_insecure_http": config.get("allow_insecure_http", False),
    }, save=False)
    assert path.read_bytes() == original, "Live configuration changed"
    assert hashlib.sha256(token_path.read_bytes()).hexdigest() == token_hash, "Live token changed"
    print(json.dumps({"connected": result["connected"], "live_config_unchanged": True,
                      "live_token_unchanged": True, "live_spool_used": False}))


if __name__ == "__main__":
    main()
