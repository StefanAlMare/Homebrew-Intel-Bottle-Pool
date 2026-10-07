"""A runnable real HTTP demo with two clients, no Brew or TrueNAS mutations."""
import secrets
import tempfile
import threading
from pathlib import Path

from pool.artifacts import manifest_for
from pool.client import Client
from pool.server import Server, Store


def main():
    with tempfile.TemporaryDirectory(prefix="intel-pool-demo-") as name:
        root = Path(name)
        token = root / "pool.token"
        token.write_text(secrets.token_hex(32))
        token.chmod(0o600)
        store = Store(root / "Diverse" / "Homebrew-Bottles")
        server = Server(("127.0.0.1", 0), store, token.read_text())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def mac(name):
                return Client({"url": "http://127.0.0.1:%d" % server.server_port,
                               "token_file": str(token), "state_dir": str(root / name)})
            a, b = mac("mac-a"), mac("mac-b")
            binary = root / "demo.pkg"
            binary.write_bytes(b"local demo binary package version 1")
            recipe = {"name": "demo/toolchain", "version": "1.0", "platform": "macos-x86_64-tahoe",
                      "variant": "default", "destination": "demo.pkg"}
            m = manifest_for(recipe, binary)
            queued = a.enqueue(m, binary)
            original_url = a.url
            a.url = "http://127.0.0.1:1"
            assert a.sync() == ["offline"] and queued.exists()
            print("Mac A: artifact preserved in spool while pool is offline")
            a.url = original_url
            assert a.sync() == ["published"]
            received = root / "mac-b.pkg"
            b.fetch(b.lookup(m), received)
            assert received.read_bytes() == binary.read_bytes()
            print("Mac B: downloaded and SHA-256 verified the artifact from Mac A")
            binary.write_bytes(b"local demo binary package version 2")
            recipe["version"] = "2.0"
            newer = manifest_for(recipe, binary)
            assert a.publish_entry(a.enqueue(newer, binary))["status"] == "published"
            blobs = [p for p in store.objects.glob("*/*") if len(p.name) == 64]
            assert len(blobs) == 1 and blobs[0].name == newer["sha256"]
            print("Server: only the latest valid version remains")
            print("LOCAL DEMO PASSED; temporary files are removed on exit")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.close()


if __name__ == "__main__":
    main()
