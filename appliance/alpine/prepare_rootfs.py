"""Sanitise a Docker-exported build tree before making a bare-metal image."""
from pathlib import Path
import sys


def prepare(root):
    root = Path(root).resolve()
    if root == Path("/") or not (root / "etc/alpine-release").is_file() or not (root / "opt/pi-home/appliance/alpine").is_dir():
        raise ValueError("Expected an extracted RoonDeck Alpine build tree, not a running system")
    for relative in (".dockerenv", "run/.containerenv"):
        marker = root / relative
        if marker.is_dir():
            raise ValueError("Unexpected directory at container marker")
        marker.unlink(missing_ok=True)
    # Docker injects these at container creation, overriding image-build values.
    for relative, text in {
        "etc/hostname": "pi-home-alpine\n",
        "etc/hosts": "127.0.0.1 localhost pi-home-alpine\n::1 localhost pi-home-alpine\n",
        "etc/resolv.conf": "# NetworkManager supplies DNS after connecting.\n",
    }.items():
        target = root / relative
        if target.is_symlink():
            raise ValueError("Unexpected symlink in exported network configuration")
        target.write_text(text)
        target.chmod(0o644)


if __name__ == "__main__":
    prepare(sys.argv[1])
