"""Private, stdin-only GUI configuration; tests never touch the live spool."""
import json
import os
import ssl
import tempfile
import uuid
from pathlib import Path

from .client import Client, RemoteError, Unavailable
from .common import PoolError, atomic_json
from .isolation import default_state_dir, require_private_path


def check_connection(client):
    try:
        health = client.json_request("GET", "health")
    except RemoteError as error:
        if error.status in (401, 403):
            raise PoolError("Authentication failed. Check the token.") from error
        raise
    except Unavailable as error:
        cause = error.__cause__
        reason = getattr(cause, "reason", cause)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise PoolError("Certificate verification failed. Check the server certificate or CA file.") from error
        raise Unavailable("Cannot connect to the server. Check its address, network/VPN, and timeout.") from error
    if not isinstance(health, dict) or health.get("schema") != 1 or health.get("status") != "ok":
        raise PoolError("The server is reachable but its Pool API is incompatible.")
    return health


def configure_gui(config_path, values, save=False):
    config_path = Path(config_path).expanduser()
    require_private_path(config_path)
    existing = json.loads(config_path.read_text()) if config_path.exists() else {}
    token = values.get("token", "").strip()
    if not token:
        token_path = values.get("token_file") or existing.get("token_file")
        if not token_path:
            raise PoolError("Paste a token or select its file.")
        token = Path(token_path).expanduser().read_text().strip()
    if not token or any(character.isspace() for character in token):
        raise PoolError("The token must be a single non-empty value.")
    config = dict(existing)
    config.update(url=values.get("url", "").strip(),
                  allow_insecure_http=bool(values.get("allow_insecure_http", False)))
    ca = values.get("ca_file", "").strip()
    config.pop("ca_file", None)
    if ca:
        config["ca_file"] = str(Path(ca).expanduser().resolve())
    config.setdefault("state_dir", str(default_state_dir()))
    require_private_path(config["state_dir"])
    config.setdefault("lock_wait_seconds", 600)
    config.setdefault("artifacts", [])
    # Tokens travel via stdin and a 0600 temporary file, never argv or logs.
    private_root = os.environ.get("HOMEBREW_POOL_TEST_ROOT")
    if private_root:
        Path(private_root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pool-connection-", dir=private_root) as temporary:
        root = Path(temporary)
        temporary_token = root / "token"
        temporary_token.write_text(token + "\n")
        temporary_token.chmod(0o600)
        candidate = dict(config, token_file=str(temporary_token), state_dir=str(root / "state"), timeout=10)
        check_connection(Client(candidate))
    if save:
        directory = config_path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Unique files leave the old configuration valid until the atomic commit.
        # Keep old credentials for rollback rather than overwriting an external file.
        suffix = uuid.uuid4().hex
        private_token = directory / ("token-" + suffix)
        descriptor = os.open(private_token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        config["token_file"] = str(private_token)
        if ca:
            private_ca = directory / ("ca-" + suffix + ".pem")
            with open(private_ca, "xb") as stream:
                stream.write(Path(ca).expanduser().read_bytes())
            private_ca.chmod(0o600)
            config["ca_file"] = str(private_ca)
        atomic_json(config_path, config)
        config_path.chmod(0o600)
    return {"connected": True, "saved": save, "message": "Healthy/Connected — authentication and Pool API verified"}
