"""Detect and remove only the superseded development-tool installations.

Scene nodes and artist-created meshes are deliberately outside this module's
scope. External WoutScales roots are accepted only when a known marker exists.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

LEGACY_PACKAGE_PREFIXES = (
    "maya_scales",
    "wout_scales",
    "bifrost_scales_integration",
)
LEGACY_MODULE_DIRECTORIES = (
    "MayaScales",
    "BifrostScalesIntegration",
    "WoutScales",
    "WoutScales2026",
)
LEGACY_MODULE_FILES = (
    "MayaScales.mod",
    "BifrostScalesIntegration.mod",
    "WoutScales.mod",
    "WoutScales2026.mod",
)
PENDING_MANIFEST_NAME = "BifrostScalesLegacyCleanupPending.json"


@dataclass(frozen=True)
class LegacyCandidate:
    label: str
    kind: str
    path: str
    external: bool
    reason: str


@dataclass(frozen=True)
class CleanupReport:
    removed: tuple[str, ...]
    skipped: tuple[str, ...]
    pending: tuple[str, ...]
    failed: tuple[str, ...]
    restart_required: bool
    manifest_path: str

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def default_module_dirs(cmds_module: Any | None = None, home: Path | None = None) -> list[Path]:
    root = Path.home() if home is None else Path(home)
    candidates: list[Path] = []
    if cmds_module is not None:
        try:
            candidates.append(Path(cmds_module.internalVar(userAppDir=True)) / "modules")
        except Exception:
            pass
    candidates.extend(
        (
            root / "maya" / "modules",
            root / "Documents" / "maya" / "modules",
        )
    )
    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = _normalized(path)
        if normalized not in seen:
            seen.add(normalized)
            result.append(path)
    return result


def scan_legacy_installations(
    cmds_module: Any | None = None,
    home: Path | None = None,
    module_dirs: Iterable[Path] | None = None,
) -> list[LegacyCandidate]:
    root = Path.home() if home is None else Path(home)
    modules = list(module_dirs or default_module_dirs(cmds_module, root))
    candidates: list[LegacyCandidate] = []

    for module_dir in modules:
        for directory_name in LEGACY_MODULE_DIRECTORIES:
            path = module_dir / directory_name
            if path.exists():
                candidates.append(
                    LegacyCandidate(
                        label=directory_name,
                        kind="module_directory",
                        path=str(path),
                        external=False,
                        reason="known legacy Maya module directory",
                    )
                )
        for file_name in LEGACY_MODULE_FILES:
            path = module_dir / file_name
            if not path.is_file():
                continue
            candidates.append(
                LegacyCandidate(
                    label=file_name,
                    kind="module_file",
                    path=str(path),
                    external=False,
                    reason="known legacy Maya module registration",
                )
            )
            candidates.extend(_candidates_from_module_file(path, modules))

    compound = root / "Autodesk" / "Bifrost" / "Compounds" / "MayaScales"
    if compound.exists():
        candidates.append(
            LegacyCandidate(
                label="MayaScales Published Compounds",
                kind="bifrost_compound",
                path=str(compound),
                external=True,
                reason="published assets owned by the superseded MayaScales tool",
            )
        )

    return _deduplicate_candidates(candidates)


def remove_legacy_installations(
    cmds_module: Any | None = None,
    include_external: bool = False,
    dry_run: bool = False,
    home: Path | None = None,
    module_dirs: Iterable[Path] | None = None,
) -> CleanupReport:
    root = Path.home() if home is None else Path(home)
    candidates = scan_legacy_installations(
        cmds_module=cmds_module,
        home=root,
        module_dirs=module_dirs,
    )
    _quiesce_loaded_legacy_packages()

    removed: list[str] = []
    skipped: list[str] = []
    pending: list[str] = []
    skipped_entries: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []
    failed: list[str] = []
    restart_required = False

    # Children first prevents a deleted parent from turning descendants into
    # misleading failures in the report.
    ordered = sorted(candidates, key=lambda item: len(Path(item.path).parts), reverse=True)
    for candidate in ordered:
        path = Path(candidate.path)
        if candidate.external and not include_external:
            skipped.append(str(path))
            skipped_entries.append(asdict(candidate))
            continue
        if not _candidate_is_safe(candidate, module_dirs or default_module_dirs(cmds_module, root)):
            failed.append("UNSAFE: {}".format(path))
            continue
        if not path.exists():
            continue
        if dry_run:
            removed.append(str(path))
            continue
        try:
            _remove_path(path)
            removed.append(str(path))
        except PermissionError:
            pending.append(str(path))
            pending_entries.append(asdict(candidate))
        except OSError as exc:
            pending.append(str(path))
            pending_entries.append(asdict(candidate))
            failed.append("{}: {}".format(path, exc))
        if "WoutScales" in candidate.label or candidate.kind in {"bifrost_pack", "bifrost_config"}:
            restart_required = True

    if pending:
        restart_required = True
    manifest_path = _manifest_path(cmds_module, root)
    manifest_payload = {
        "schema": "bifrost-scales/legacy-cleanup/1",
        "pending": pending,
        "skipped_external": skipped,
        "pending_entries": pending_entries,
        "skipped_external_entries": skipped_entries,
        "restart_required": restart_required,
    }
    if not dry_run:
        if pending or skipped:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError:
                pass

    return CleanupReport(
        removed=tuple(removed),
        skipped=tuple(skipped),
        pending=tuple(pending),
        failed=tuple(failed),
        restart_required=restart_required,
        manifest_path=str(manifest_path),
    )


def complete_pending_cleanup(manifest_path: str | Path) -> CleanupReport:
    manifest = Path(manifest_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    structured = list(payload.get("pending_entries", ()))
    structured.extend(payload.get("skipped_external_entries", ()))
    if structured:
        targets = [Path(value["path"]) for value in structured if value.get("path")]
    else:
        targets = [Path(value) for value in payload.get("pending", ())]
        targets.extend(Path(value) for value in payload.get("skipped_external", ()))
    removed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    for path in sorted(set(targets), key=lambda item: len(item.parts), reverse=True):
        if not path.exists():
            continue
        if not _standalone_path_is_safe(path):
            failed.append("UNSAFE: {}".format(path))
            continue
        try:
            _remove_path(path)
            removed.append(str(path))
        except OSError as exc:
            pending.append(str(path))
            failed.append("{}: {}".format(path, exc))
    if pending:
        payload["pending"] = pending
        payload["skipped_external"] = []
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        try:
            manifest.unlink()
        except OSError:
            pass
    return CleanupReport(
        removed=tuple(removed),
        skipped=(),
        pending=tuple(pending),
        failed=tuple(failed),
        restart_required=bool(pending),
        manifest_path=str(manifest),
    )


def _candidates_from_module_file(path: Path, module_dirs: list[Path]) -> list[LegacyCandidate]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    result: list[LegacyCandidate] = []
    module_root: Path | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^\+\s+\S+\s+\S+\s+(.+)$", line)
        if match:
            module_root = _resolve_module_value(match.group(1), path.parent)
            if module_root and module_root.exists() and _legacy_marker_exists(module_root):
                result.append(
                    LegacyCandidate(
                        label="{} external root".format(path.stem),
                        kind="external_module_root",
                        path=str(module_root),
                        external=not _is_inside_any(module_root, module_dirs),
                        reason="legacy module root declared by {}".format(path.name),
                    )
                )
            continue
        if "BIFROST_LIB_CONFIG_FILES" not in line:
            continue
        value = _environment_assignment_value(line)
        if not value:
            continue
        config = _resolve_module_value(value, module_root or path.parent)
        if config is None or not config.exists():
            continue
        if config.is_file() and "woutscales" in config.name.lower():
            result.append(
                LegacyCandidate(
                    label="WoutScales Bifrost config",
                    kind="bifrost_config",
                    path=str(config),
                    external=True,
                    reason="WoutScales BIFROST_LIB_CONFIG_FILES registration",
                )
            )
            pack_root = config.parent
            if _legacy_marker_exists(pack_root):
                result.append(
                    LegacyCandidate(
                        label="WoutScales Bifrost pack",
                        kind="bifrost_pack",
                        path=str(pack_root),
                        external=True,
                        reason="pack directory owning the legacy config",
                    )
                )
    return result


def _environment_assignment_value(line: str) -> str:
    for token in ("+:=", ":=", "="):
        if token in line:
            return line.split(token, 1)[1].strip().strip('"').strip("'")
    return ""


def _resolve_module_value(value: str, base: Path) -> Path | None:
    expanded = os.path.expandvars(os.path.expanduser(value.strip().strip('"').strip("'")))
    if not expanded or "$" in expanded or "%" in expanded:
        return None
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate


def _legacy_marker_exists(path: Path) -> bool:
    markers = (
        path / "scripts" / "maya_scales" / "__init__.py",
        path / "MayaScales" / "scripts" / "maya_scales" / "__init__.py",
        path / "scripts" / "wout_scales" / "__init__.py",
        path / "scripts" / "bifrost_scales_integration" / "__init__.py",
        path / "WoutScalesPackConfig.json",
        path / "BifrostScalesIntegration.mod",
        path / "MayaScales.mod",
    )
    if any(marker.exists() for marker in markers):
        return True
    lowered = path.name.lower()
    return lowered.startswith("woutscales-") and any(path.glob("*PackConfig.json"))


def _candidate_is_safe(candidate: LegacyCandidate, module_dirs: Iterable[Path]) -> bool:
    path = Path(candidate.path)
    if path.name in LEGACY_MODULE_FILES:
        return True
    if any(path == module_dir / name for module_dir in module_dirs for name in LEGACY_MODULE_DIRECTORIES):
        return True
    if candidate.kind == "bifrost_compound":
        return path.name == "MayaScales" and path.parent.name == "Compounds"
    if candidate.kind == "bifrost_config":
        return path.is_file() and "woutscales" in path.name.lower()
    return _legacy_marker_exists(path)


def _standalone_path_is_safe(path: Path) -> bool:
    if path.name in LEGACY_MODULE_FILES or path.name in LEGACY_MODULE_DIRECTORIES:
        return True
    if path.name == "MayaScales" and path.parent.name == "Compounds":
        return True
    if path.is_file() and "woutscales" in path.name.lower() and path.suffix.lower() == ".json":
        return True
    return _legacy_marker_exists(path)


def _deduplicate_candidates(candidates: Iterable[LegacyCandidate]) -> list[LegacyCandidate]:
    result: list[LegacyCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _normalized(Path(candidate.path))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return sorted(result, key=lambda item: (item.label.lower(), item.path.lower()))


def _is_inside_any(path: Path, roots: Iterable[Path]) -> bool:
    normalized = Path(path).resolve(strict=False)
    for root in roots:
        try:
            normalized.relative_to(Path(root).resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def _normalized(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except OSError:
        return os.path.normcase(str(path))


def _quiesce_loaded_legacy_packages() -> None:
    draw_module = sys.modules.get("maya_scales.draw_context")
    stop_draw = getattr(draw_module, "stop_draw", None) if draw_module is not None else None
    if callable(stop_draw):
        try:
            stop_draw()
        except Exception:
            pass
    for ui_name in (
        "maya_scales.ui",
        "wout_scales.ui",
        "bifrost_scales_integration.ui",
    ):
        module = sys.modules.get(ui_name)
        window = getattr(module, "_WINDOW", None) if module is not None else None
        if window is not None:
            try:
                window.close()
                window.deleteLater()
            except Exception:
                pass
    for name in sorted(tuple(sys.modules), key=len, reverse=True):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in LEGACY_PACKAGE_PREFIXES):
            sys.modules.pop(name, None)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(str(path), onerror=_remove_read_only)
    else:
        try:
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
        path.unlink()


def _remove_read_only(function, path, _exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        function(path)
    except OSError:
        raise


def _manifest_path(cmds_module: Any | None, home: Path) -> Path:
    if cmds_module is not None:
        try:
            return Path(cmds_module.internalVar(userAppDir=True)) / PENDING_MANIFEST_NAME
        except Exception:
            pass
    return home / PENDING_MANIFEST_NAME
