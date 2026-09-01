"""Install the current verified development build without creating a ZIP."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import build_one_click_installer as bundle


ROOT = Path(__file__).resolve().parents[1]


def install_dev_build(modules_dir: Path | None = None) -> None:
    runtime = bundle._runtime_files(ROOT)
    with tempfile.TemporaryDirectory(
        prefix="bifrost_scales_dev_install_",
        dir=ROOT / "native" / "build",
    ) as temporary:
        stage = Path(temporary)
        payload = stage / "payload"
        entries = [("BifrostScales.mod", bundle._CANONICAL_MOD.encode("utf-8"))]
        entries.extend(
            (archive_name, source.read_bytes())
            for source, archive_name in runtime
        )
        entries.sort(key=lambda item: item[0])
        hashes = {name: bundle._sha256_bytes(data) for name, data in entries}
        manifest = {
            "schema": "bifrost-scales/one-click-payload/1",
            "product": "Bifrost Scales",
            "version": bundle.VERSION,
            "platform": "windows-x64",
            "maya_version": 2026,
            "pack": bundle.PACK_NAME,
            "files": hashes,
        }
        for name, data in entries:
            destination = payload / Path(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (stage / "payload_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        command = [
            sys.executable,
            str(ROOT / "installer" / "offline_install.py"),
            "--bundle-root",
            str(stage),
        ]
        if modules_dir is not None:
            command.extend(("--modules-dir", str(modules_dir)))
        subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules-dir", type=Path)
    arguments = parser.parse_args()
    install_dev_build(arguments.modules_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
