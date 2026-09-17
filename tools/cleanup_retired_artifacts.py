"""Archive and remove an exact allowlist of superseded generated artifacts."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ("BifrostScales_0_10_8_Standalone_Installer.py",
           "BifrostScales_0_10_8_POST_INSTALL_CHECK.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    files = [ROOT / name for name in RETIRED if (ROOT / name).is_file()]
    for path in files:
        if path.is_symlink() or path.resolve().parent != ROOT:
            raise RuntimeError("Refusing cleanup outside the workspace root")
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    report = {"files": manifest, "bytes": sum(path.stat().st_size for path in files), "removed": False}
    if args.apply and files:
        archive = ROOT / "native/build" / ("retired-artifacts-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".zip")
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
            for path in files:
                output.write(path, path.name)
            output.writestr("manifest.json", json.dumps(manifest, indent=2))
        with zipfile.ZipFile(archive) as check:
            for path in files:
                assert hashlib.sha256(check.read(path.name)).hexdigest() == manifest[path.name]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[path.name]
        for path in files:
            path.unlink()
        report.update(removed=True, recovery=str(archive))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
