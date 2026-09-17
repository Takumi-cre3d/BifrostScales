"""Build the Maya Native Pack twice and compare distributable bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "BifrostScales" / "bifrost" / "tools" / "Build-BifrostScales-Native-Maya2026.ps1"
PACK = ROOT / "BifrostScales" / "bifrost" / "pack" / "BifrostScalesCore-0.10.9"
MOD = ROOT / "BifrostScales.mod"
IGNORED_SUFFIXES = {".exp", ".ilk", ".lib", ".pdb"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, str]:
    return {
        path.relative_to(PACK).as_posix(): _sha(path)
        for path in sorted(PACK.rglob("*"))
        if path.is_file() and path.suffix.lower() not in IGNORED_SUFFIXES
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    original_mod = MOD.read_bytes()
    manifests: list[dict[str, str]] = []
    try:
        for label in ("a", "b"):
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(BUILD),
                    "-Configuration",
                    "Release",
                    "-Clean",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output.with_name(output.stem + "-" + label + ".log").write_text(
                completed.stdout, encoding="utf-8"
            )
            if completed.returncode:
                raise RuntimeError("Native build {} failed; see its log".format(label))
            manifests.append(_manifest())
    finally:
        MOD.write_bytes(original_mod)

    differing = sorted(
        name
        for name in set(manifests[0]) | set(manifests[1])
        if manifests[0].get(name) != manifests[1].get(name)
    )
    report = {
        "schema": "bifrost-scales/native-build-reproducibility/1",
        "success": not differing,
        "payload_files": len(manifests[1]),
        "differing_files": differing,
        "pack_manifest": manifests[1],
        "module_restored_sha256": hashlib.sha256(MOD.read_bytes()).hexdigest(),
    }
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
