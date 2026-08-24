"""Build deterministic runtime payload, installer, source ZIP, and checksums."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.10.6"
INSTALLER_NAME = "BifrostScales_0_10_6_Standalone_Installer.py"
SOURCE_ZIP_NAME = "BifrostScales_0_10_6.zip"
FIXED_TIME = (2026, 8, 21, 0, 0, 0)


def _zip_bytes(paths: list[tuple[Path, str]]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, archive_name in sorted(paths, key=lambda item: item[1]):
            info = zipfile.ZipInfo(archive_name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, source.read_bytes())
    return buffer.getvalue()


def _runtime_paths() -> list[tuple[Path, str]]:
    result = [(ROOT / "BifrostScales.mod", "BifrostScales.mod")]
    package = ROOT / "BifrostScales"
    for path in package.rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
            or "out" in path.parts
        ):
            continue
        result.append((path, path.relative_to(ROOT).as_posix()))

    # The standalone Maya installer includes the native source as part of the
    # module so the user can build the Bifrost Operator Pack in place with the
    # supplied PowerShell script. Build outputs are intentionally excluded.
    native = ROOT / "native"
    for path in native.rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
            or any(part.startswith("build") or part == "out" for part in path.parts)
        ):
            continue
        archive_name = "BifrostScales/bifrost/native/{}".format(
            path.relative_to(native).as_posix()
        )
        result.append((path, archive_name))
    return result


def _installer_source(payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(payload).decode("ascii")
    chunks = "\n".join("    {!r}".format(encoded[index:index + 96]) for index in range(0, len(encoded), 96))
    return f'''"""Standalone installer for Bifrost Scales {VERSION}.

Drag this file into a Maya 2026 viewport.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

_VERSION = {VERSION!r}
_PAYLOAD_SHA256 = {digest!r}
_PAYLOAD_B64 = (\n{chunks}\n)
LAST_CLEANUP_REPORT = None
LAST_INSTALL_REPORT = None
_INSTALL_BACKUP_PACKAGE_PREFIX = "BifrostScales.__install_backup__"
_INSTALL_BACKUP_MOD_PREFIX = "BifrostScales.mod.__install_backup__"


def _path_exists(path):
    return path.exists() or path.is_symlink()


def _remove_read_only(function, path, _exc_info):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    function(path)


def _remove_path(path):
    path = Path(path)
    if not _path_exists(path):
        return True
    try:
        is_junction = bool(getattr(path, "is_junction", lambda: False)())
    except OSError:
        is_junction = False
    try:
        if path.is_symlink() or is_junction or path.is_file():
            try:
                os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            path.unlink()
        else:
            shutil.rmtree(str(path), onerror=_remove_read_only)
    except OSError:
        return False
    return not _path_exists(path)


def _path_mtime(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _list_install_backups(modules_dir, prefix):
    if not modules_dir.is_dir():
        return []
    result = [
        entry
        for entry in modules_dir.iterdir()
        if entry.name == prefix or entry.name.startswith(prefix + ".")
    ]
    return sorted(result, key=lambda item: (_path_mtime(item), item.name))


def _allocate_transaction_backup(modules_dir, prefix):
    while True:
        candidate = modules_dir / (prefix + "." + uuid.uuid4().hex)
        if not _path_exists(candidate):
            return candidate


def _unload_package():
    for name in sorted(tuple(sys.modules), key=len, reverse=True):
        if name == "bifrost_scales" or name.startswith("bifrost_scales."):
            sys.modules.pop(name, None)


def _close_running_tool():
    picker_module = sys.modules.get("bifrost_scales.cell_picker_maya")
    disable_picker = getattr(picker_module, "disable_cell_picker", None) if picker_module is not None else None
    if callable(disable_picker):
        try:
            disable_picker()
        except Exception:
            pass
    try:
        import maya.cmds as _cmds  # type: ignore
        for _plugin_name in ("bifrostScalesCellPicker.py", "bifrostScalesCellPicker"):
            try:
                if _cmds.pluginInfo(_plugin_name, query=True, loaded=True):
                    _cmds.unloadPlugin(_plugin_name, force=True)
                    break
            except Exception:
                pass
    except Exception:
        pass
    draw_module = sys.modules.get("bifrost_scales.draw_context")
    stop_draw = getattr(draw_module, "stop_draw", None) if draw_module is not None else None
    if callable(stop_draw):
        try:
            stop_draw(cancel=True, reason="Bifrost Scales更新のためGuide描画を終了しました")
        except Exception:
            pass
    module = sys.modules.get("bifrost_scales.ui")
    window = getattr(module, "_WINDOW", None) if module is not None else None
    if window is not None:
        try:
            window.close()
            window.deleteLater()
        except Exception:
            pass


def _payload_bytes():
    try:
        payload = base64.b64decode("".join(_PAYLOAD_B64), validate=True)
    except Exception as exc:
        raise RuntimeError("The embedded Bifrost Scales payload is invalid") from exc
    if hashlib.sha256(payload).hexdigest() != _PAYLOAD_SHA256:
        raise RuntimeError("The Bifrost Scales payload failed integrity verification")
    return payload


def _extract_payload(destination):
    with zipfile.ZipFile(io.BytesIO(_payload_bytes()), "r") as archive:
        names = set()
        for member in archive.infolist():
            normalized = PurePosixPath(member.filename)
            if normalized.is_absolute() or ".." in normalized.parts:
                raise RuntimeError("The installer payload contains an unsafe path")
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError("The installer payload contains an unsupported symbolic link")
            names.add(member.filename.rstrip("/"))
        required = {{
            "BifrostScales.mod",
            "BifrostScales/scripts/bifrost_scales/__init__.py",
            "BifrostScales/scripts/bifrost_scales/backend.py",
            "BifrostScales/scripts/bifrost_scales/cell_picker_core.py",
            "BifrostScales/scripts/bifrost_scales/cell_picker_maya.py",
            "BifrostScales/scripts/bifrost_scales/cell_identity.py",
            "BifrostScales/plug-ins/bifrostScalesCellPicker.py",
            "BifrostScales/scripts/bifrost_scales/backend_protocol.py",
            "BifrostScales/scripts/bifrost_scales/diagnostics.py",
            "BifrostScales/scripts/bifrost_scales/draw_context.py",
            "BifrostScales/scripts/bifrost_scales/guides.py",
            "BifrostScales/scripts/bifrost_scales/legacy_cleanup.py",
            "BifrostScales/scripts/bifrost_scales/math3d.py",
            "BifrostScales/scripts/bifrost_scales/native_backend.py",
            "BifrostScales/scripts/bifrost_scales/native_payload.py",
            "BifrostScales/scripts/bifrost_scales/native_smoke.py",
            "BifrostScales/bifrost/compounds/BifrostScales_native_scales_v4_graph.json",
            "BifrostScales/bifrost/compounds/manifest.bifrost-scales.json",
            "BifrostScales/bifrost/tools/Build-BifrostScales-Native-Maya2026.ps1",
            "BifrostScales/bifrost/native/CMakeLists.txt",
            "BifrostScales/bifrost/native/include/bifrost_scales/core.hpp",
            "BifrostScales/bifrost/native/include/bifrost_scales/payload.hpp",
            "BifrostScales/bifrost/native/src/core.cpp",
            "BifrostScales/bifrost/native/src/payload.cpp",
            "BifrostScales/bifrost/native/include/bifrost_scales/gpu_compute.hpp",
            "BifrostScales/bifrost/native/src/gpu_compute.cpp",
            "BifrostScales/bifrost/native/include/bifrost_scales/preview_distribution.hpp",
            "BifrostScales/bifrost/native/src/preview_distribution.cpp",
            "BifrostScales/bifrost/native/operator/CMakeLists.txt",
            "BifrostScales/bifrost/native/operator/PackConfig.json.in",
            "BifrostScales/bifrost/native/operator/src/bifrost_scales_nodedef.hpp",
            "BifrostScales/bifrost/native/operator/src/bifrost_scales_nodedef.cpp",
            "BifrostScales/bifrost/native/operator/src/bifrost_scales_operator_export.hpp",
            "BifrostScales/bifrost/native/tests/core_tests.cpp",
            "BifrostScales/bifrost/native/tools/interactive_distribution_benchmark.cpp",
            "BifrostScales/bifrost/native/tools/candidate_batch_benchmark.cpp",
            "BifrostScales/bifrost/native/tools/parity_dump.cpp",
            "BifrostScales/bifrost/native/tools/stage_cache_benchmark.cpp",
            "BifrostScales/bifrost/native/bifrost/operator_contract.json",
            "BifrostScales/scripts/bifrost_scales/parameter_controls.py",
            "BifrostScales/scripts/bifrost_scales/parameter_mapping.py",
            "BifrostScales/scripts/bifrost_scales/qt_compat.py",
            "BifrostScales/scripts/bifrost_scales/qt_scheduler.py",
            "BifrostScales/scripts/bifrost_scales/scene.py",
            "BifrostScales/scripts/bifrost_scales/scheduler.py",
            "BifrostScales/scripts/bifrost_scales/settings.py",
            "BifrostScales/scripts/bifrost_scales/ui.py",
            "BifrostScales/scripts/bifrost_scales/version.py",
        }}
        if not required.issubset(names):
            raise RuntimeError("The embedded Bifrost Scales payload is incomplete")
        archive.extractall(str(destination))


def _restore(destination, backup):
    if _path_exists(destination) and not _remove_path(destination):
        raise RuntimeError(
            "Rollback could not remove the incomplete install: " + str(destination)
        )
    if _path_exists(backup):
        backup.rename(destination)


def _merge_directory(source, destination):
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(str(child), str(target), dirs_exist_ok=True)
        else:
            shutil.copy2(str(child), str(target))


def _preserve_native_pack(backup_package, destination_package):
    if not backup_package.is_dir():
        return
    # Only the installed Pack is reusable runtime state. ``bifrost/out`` is a
    # transient CMake/MSBuild tree and can contain generated .tlog paths that
    # exceed the legacy Windows path limit once the package is renamed to a
    # transaction backup. Copying that tree is unnecessary (release updates
    # require ``-Clean``) and made an otherwise valid install fail in Maya.
    relative = Path("bifrost") / "pack"
    _merge_directory(backup_package / relative, destination_package / relative)


def _preserve_native_packs_from_backups(backups, destination_package):
    for backup_package in backups:
        _preserve_native_pack(backup_package, destination_package)


def _native_pack_configs(package_root):
    pack_container = package_root / "bifrost" / "pack"
    if not pack_container.is_dir():
        return []
    return sorted(
        pack_container.rglob("BifrostScalesPackConfig.json"),
        key=lambda item: (item.parent.name, item.as_posix()),
        reverse=True,
    )


def _find_operator_nodedef(pack_root):
    json_root = pack_root / "json"
    if not json_root.is_dir():
        return None
    preferred = (
        json_root
        / "BifrostScales"
        / "operators"
        / "bifrost_scales_nodedef.json"
    )
    if preferred.is_file():
        return preferred
    matches = sorted(json_root.rglob("bifrost_scales_nodedef.json"))
    return matches[0] if matches else None


def _native_pack_version(pack_config):
    """Return the declared pack version without trusting directory mtime."""

    if not pack_config.is_file():
        return ()
    try:
        data = json.loads(pack_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        data = {{}}
    values = []
    for configuration in data.get("AminoConfigurations", []):
        if isinstance(configuration, dict):
            values.append(str(configuration.get("libraryVersion", "") or ""))
    values.append(pack_config.parent.name.rsplit("-", 1)[-1])
    for value in values:
        match = re.match(r"^(\\d+)\\.(\\d+)\\.(\\d+)", value)
        if match:
            return tuple(int(part) for part in match.groups())
    return ()


def _nodedef_has_uint_topology_contract(nodedef):
    if not nodedef.is_file():
        return False
    try:
        data = json.loads(nodedef.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    expected = {{
        "source_face_offset": "array<uint>",
        "source_face_vertex": "array<uint>",
        "face_offset": "array<uint>",
        "face_vertex": "array<uint>",
        "profile_json": "string",
    }}
    for operator_entry in data.get("operators", []):
        if not isinstance(operator_entry, dict):
            continue
        if str(operator_entry.get("name", "")) != "BifrostScales::generate_scale_mesh_payload_arrays":
            continue
        port_types = {{
            str(port.get("portName", "")): str(port.get("portType", ""))
            for port in operator_entry.get("ports", [])
            if isinstance(port, dict)
        }}
        return all(port_types.get(name) == port_type for name, port_type in expected.items())
    return False


def _normalized_native_path(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _graph_has_input_by_path_contract(graph):
    if not graph.is_file():
        return False
    try:
        data = json.loads(graph.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    compounds = data.get("compounds", []) if isinstance(data, dict) else []
    if not isinstance(compounds, list) or len(compounds) != 1:
        return False
    compound = compounds[0]
    if not isinstance(compound, dict):
        return False
    if str(compound.get("name", "")) != "Graphs::BifrostScales::native_scales_v4":
        return False
    graph_marker = next(
        (
            entry for entry in compound.get("metadata", [])
            if isinstance(entry, dict) and entry.get("metaName") == "compoundIsGraph"
        ),
        None,
    )
    if not isinstance(graph_marker, dict) or str(graph_marker.get("metaValue", "")).lower() != "true":
        return False
    source_port = next(
        (
            port for port in compound.get("ports", [])
            if isinstance(port, dict) and port.get("portName") == "source_mesh"
        ),
        None,
    )
    if not isinstance(source_port, dict) or source_port.get("portType") != "Object":
        return False
    pathinfo = next(
        (
            entry for entry in source_port.get("metadata", [])
            if isinstance(entry, dict) and entry.get("metaName") == "pathinfo"
        ),
        None,
    )
    if not isinstance(pathinfo, dict):
        return False
    leaves = {{
        str(entry.get("metaName", "")): entry
        for entry in pathinfo.get("metadata", [])
        if isinstance(entry, dict)
    }}
    for name in ("path", "setOperation", "active"):
        entry = leaves.get(name)
        if not isinstance(entry, dict) or entry.get("metaType") != "string":
            return False
    if str(leaves["active"].get("metaValue", "")).lower() != "true":
        return False
    if str(leaves["setOperation"].get("metaValue", "")) != "+":
        return False
    connections = {{
        (str(item.get("source", "")), str(item.get("target", "")))
        for item in compound.get("connections", [])
        if isinstance(item, dict)
    }}
    return (".source_mesh", "get_mesh_structure.mesh") in connections


def _graph_payload_schema(graph):
    if not graph.is_file():
        return ""
    try:
        data = json.loads(graph.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    compounds = data.get("compounds", []) if isinstance(data, dict) else []
    if not isinstance(compounds, list) or len(compounds) != 1:
        return ""
    compound = compounds[0]
    if not isinstance(compound, dict):
        return ""
    payload_port = next(
        (
            port for port in compound.get("ports", [])
            if isinstance(port, dict) and port.get("portName") == "payload_json"
        ),
        None,
    )
    if not isinstance(payload_port, dict):
        return ""
    try:
        payload = json.loads(str(payload_port.get("portDefault", "") or ""))
    except (ValueError, TypeError):
        return ""
    return str(payload.get("schema", "") or "") if isinstance(payload, dict) else ""


def _manifest_payload_schema(manifest):
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(data.get("native_payload_schema", "") or "") if isinstance(data, dict) else ""


def _manifest_behavior_contract(manifest):
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(data.get("native_behavior_contract", "") or "") if isinstance(data, dict) else ""


def _manifest_profile_schema(manifest):
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(data.get("native_profile_schema", "") or "") if isinstance(data, dict) else ""


def _operator_compatible_native_pack(pack_config):
    """Return whether an existing 0.10.6 Native Pack satisfies this release.

    Payload Schema 10 and Static Graph v4 remain stable, but the OpenCL GPU
    execution layer, density-adaptive boundary placement, Operator Contract
    16, Behavior Contract, and Profile Schema 8 must all match. Version alone
    is insufficient because an older DLL cannot execute these boundaries.
    """

    version = _native_pack_version(pack_config)
    if version < (0, 10, 4):
        return False
    if not pack_config.is_file():
        return False
    pack_root = pack_config.parent
    operator = pack_root / "lib" / "BifrostScalesOps.dll"
    nodedef = _find_operator_nodedef(pack_root)
    graph = (
        pack_root
        / "json"
        / "BifrostScales"
        / "graphs"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    manifest = pack_root / "metadata" / "manifest.bifrost-scales.json"
    return bool(
        operator.is_file()
        and nodedef is not None
        and _nodedef_has_uint_topology_contract(nodedef)
        and _graph_payload_schema(graph) == "bifrost-scales/native-payload/10"
        and _manifest_payload_schema(manifest)
        == "bifrost-scales/native-payload/10"
        and _manifest_behavior_contract(manifest)
        == "bifrost-scales/native-core/0.10.6-cell-hot-path-1"
        and _manifest_profile_schema(manifest)
        == "bifrost-scales/native-profile/9"
    )


def _native_version_text(pack_config):
    try:
        data = json.loads(pack_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        data = {{}}
    for configuration_entry in data.get("AminoConfigurations", []):
        if isinstance(configuration_entry, dict):
            value = str(configuration_entry.get("libraryVersion", "") or "")
            if re.match(r"^\\d+\\.\\d+\\.\\d+", value):
                return value
    version = _native_pack_version(pack_config)
    return ".".join(str(part) for part in version) if version else "0.10.6"


def _upgrade_native_pack_graph_contract(pack_config, package_root):
    """Normalize a compatible 0.10.6+ pack to the graph-v4 scene-input contract."""

    if not _operator_compatible_native_pack(pack_config):
        return False
    source_graph = (
        package_root
        / "bifrost"
        / "compounds"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    source_manifest = (
        package_root
        / "bifrost"
        / "compounds"
        / "manifest.bifrost-scales.json"
    )
    if not _graph_has_input_by_path_contract(source_graph):
        return False
    if _graph_payload_schema(source_graph) != "bifrost-scales/native-payload/10":
        return False

    pack_root = pack_config.parent
    graph_dir = pack_root / "json" / "BifrostScales" / "graphs"
    operator_dir = pack_root / "json" / "BifrostScales" / "operators"
    metadata_dir = pack_root / "metadata"
    graph_dir.mkdir(parents=True, exist_ok=True)
    operator_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    nodedef = _find_operator_nodedef(pack_root)
    preferred_nodedef = operator_dir / "bifrost_scales_nodedef.json"
    if nodedef is None:
        return False
    if _normalized_native_path(nodedef) != _normalized_native_path(preferred_nodedef):
        shutil.copy2(str(nodedef), str(preferred_nodedef))

    installed_graph = graph_dir / "BifrostScales_native_scales_v4_graph.json"
    shutil.copy2(str(source_graph), str(installed_graph))
    if not _graph_has_input_by_path_contract(installed_graph):
        return False
    if _graph_payload_schema(installed_graph) != "bifrost-scales/native-payload/10":
        return False

    manifest_target = metadata_dir / "manifest.bifrost-scales.json"
    try:
        manifest_data = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        manifest_data = {{}}
    manifest_data.update({{
        "product": "Bifrost Scales",
        "version": _VERSION,
        "native_pack_version": _native_version_text(pack_config),
        "graph_definition": "Graphs::BifrostScales::native_scales_v4",
        "graph_asset_revision": 4,
        "graph_input_contract": "top-level-object-plus-maya-dg-worldMesh",
        "operator": "BifrostScales::generate_scale_mesh_payload_arrays",
    }})
    manifest_target.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
        newline="\\n",
    )

    configuration = {{
        "vendorName": "BifrostScales",
        "libraryVersion": _native_version_text(pack_config),
        "libraryName": "BifrostScales",
        "sharedLibs": [{{"path": "./lib", "files": ["BifrostScalesOps"]}}],
        "jsonLibs": [
            {{
                "path": "./json/BifrostScales/operators",
                "files": ["bifrost_scales_nodedef.json"],
            }},
            {{
                "path": "./json/BifrostScales/graphs",
                "files": ["BifrostScales_native_scales_v4_graph.json"],
            }},
        ],
    }}
    pack_config.write_text(
        json.dumps({{"AminoConfigurations": [configuration]}}, indent=2) + "\\n",
        encoding="utf-8",
        newline="\\n",
    )

    # Remove only known obsolete copies after the v4 graph and preferred
    # nodedef have been written successfully. Unknown user files are untouched.
    for obsolete in (
        graph_dir / "BifrostScales_native_scales_v3_graph.json",
        pack_root / "json" / "BifrostScales" / "BifrostScales_native_scales_v3_graph.json",
        pack_root / "json" / "BifrostScales" / "BifrostScales_native_scales_v4_graph.json",
        pack_root / "json" / "BifrostScales" / "bifrost_scales_nodedef.json",
        pack_root / "json" / "BifrostScales" / "manifest.bifrost-scales.json",
    ):
        try:
            if obsolete.is_file() and _normalized_native_path(obsolete) not in {{
                _normalized_native_path(installed_graph),
                _normalized_native_path(preferred_nodedef),
                _normalized_native_path(manifest_target),
            }}:
                obsolete.unlink()
        except OSError:
            pass
    return _is_valid_native_pack_config(pack_config)


def _is_valid_native_pack_config(pack_config):
    if not pack_config.is_file():
        return False
    pack_root = pack_config.parent
    operator = pack_root / "lib" / "BifrostScalesOps.dll"
    nodedef = (
        pack_root
        / "json"
        / "BifrostScales"
        / "operators"
        / "bifrost_scales_nodedef.json"
    )
    graph = (
        pack_root
        / "json"
        / "BifrostScales"
        / "graphs"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    manifest = pack_root / "metadata" / "manifest.bifrost-scales.json"
    if not all(path.is_file() for path in (operator, nodedef, graph, manifest)):
        return False
    if not _nodedef_has_uint_topology_contract(nodedef):
        return False
    if not _graph_has_input_by_path_contract(graph):
        return False
    if _graph_payload_schema(graph) != "bifrost-scales/native-payload/10":
        return False
    if _manifest_payload_schema(manifest) != "bifrost-scales/native-payload/10":
        return False
    if _manifest_behavior_contract(manifest) != "bifrost-scales/native-core/0.10.6-cell-hot-path-1":
        return False
    if _manifest_profile_schema(manifest) != "bifrost-scales/native-profile/9":
        return False
    try:
        data = json.loads(pack_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    expected = [
        (
            "./json/BifrostScales/operators",
            ["bifrost_scales_nodedef.json"],
        ),
        (
            "./json/BifrostScales/graphs",
            ["BifrostScales_native_scales_v4_graph.json"],
        ),
    ]
    for configuration_entry in data.get("AminoConfigurations", []):
        if not isinstance(configuration_entry, dict):
            continue
        libraries = configuration_entry.get("jsonLibs")
        if not isinstance(libraries, list) or len(libraries) < 2:
            continue
        normalized = []
        for library in libraries:
            if not isinstance(library, dict):
                continue
            path = str(library.get("path", "") or "").replace("\\\\", "/").rstrip("/")
            files = [str(item) for item in library.get("files", [])]
            normalized.append((path, files))
        if normalized[:2] == expected:
            return True
    return False


def _is_namespace_fixed_native_pack(pack_config):
    """Backward-compatible helper name for the complete graph-v4 contract."""

    return _is_valid_native_pack_config(pack_config)


def _register_existing_native_pack(package_root, mod_file):
    selected = None
    for candidate in _native_pack_configs(package_root):
        if not _operator_compatible_native_pack(candidate):
            continue
        if _upgrade_native_pack_graph_contract(candidate, package_root):
            selected = candidate
            break
    if selected is None:
        return ""
    module_text = (
        "+ BifrostScales {VERSION} "
        + package_root.as_posix()
        + "\\nPYTHONPATH +:= scripts"
        + "\\nPATH +:= bin"
        + "\\nplug-ins: plug-ins"
        + "\\nBIFROST_LIB_CONFIG_FILES += "
        + selected.as_posix()
        + "\\n"
    )
    mod_file.write_text(module_text, encoding="utf-8", newline="\\n")
    return str(selected)

def _has_preserved_incompatible_native_pack(package_root):
    return any(
        not _operator_compatible_native_pack(candidate)
        for candidate in _native_pack_configs(package_root)
    )


def _mod_registers_native_pack(mod_file, pack_config):
    if not pack_config or not mod_file.is_file():
        return False
    try:
        module_text = mod_file.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    expected = "BIFROST_LIB_CONFIG_FILES += " + Path(pack_config).as_posix()
    return expected in module_text.replace("\\\\", "/")


def _installation_choice(cmds):
    choice = cmds.confirmDialog(
        title="Install Bifrost Scales",
        message=(
            "Bifrost Scales {VERSION}を独立製品としてインストールします。\\n"
            "0.10.6はSettled Cell Partitionの正確な結果を維持したまま、共通Ray表、近傍Metadata事前計算、Maskなし高速経路でCellsを短縮します。\\n"
            "互換Native Packがない場合のみ、同梱PowerShellでOperator PackをビルドしてMayaを再起動してください。\\n"
            "旧ツールを削除してもシーン内の制作データは削除しません。"
        ),
        button=["インストール＋旧ツール削除", "インストールのみ", "キャンセル"],
        defaultButton="インストール＋旧ツール削除",
        cancelButton="キャンセル",
        dismissString="キャンセル",
    )
    if choice == "キャンセル":
        return None
    return choice == "インストール＋旧ツール削除"


def install(show_tool=True, remove_legacy=None):
    import maya.cmds as cmds  # type: ignore

    global LAST_CLEANUP_REPORT, LAST_INSTALL_REPORT
    LAST_INSTALL_REPORT = None
    if remove_legacy is None:
        remove_legacy = _installation_choice(cmds)
        if remove_legacy is None:
            return None

    staging_root = Path(tempfile.mkdtemp(prefix="BifrostScales_0_10_6_"))
    modules_dir = Path(cmds.internalVar(userAppDir=True)) / "modules"
    destination_package = modules_dir / "BifrostScales"
    destination_mod = modules_dir / "BifrostScales.mod"
    preserved_native_pack = ""
    incompatible_native_pack_preserved = False
    pending_backup_cleanup = []
    stale_package_backups = []
    stale_mod_backups = []
    discarded_transient_build_trees = 0
    backup_package = None
    backup_mod = None
    package_moved = False
    mod_moved = False

    try:
        _extract_payload(staging_root)
        staged_package = staging_root / "BifrostScales"
        staged_mod = staging_root / "BifrostScales.mod"
        modules_dir.mkdir(parents=True, exist_ok=True)
        _close_running_tool()
        _unload_package()

        # 0.8.2 and earlier used one fixed backup name. A loaded Native DLL can
        # make that folder undeletable until Maya exits. Do not reuse or require
        # deletion of any stale backup; each transaction gets a unique path.
        stale_package_backups = _list_install_backups(
            modules_dir, _INSTALL_BACKUP_PACKAGE_PREFIX
        )
        stale_mod_backups = _list_install_backups(
            modules_dir, _INSTALL_BACKUP_MOD_PREFIX
        )
        backup_package = _allocate_transaction_backup(
            modules_dir, _INSTALL_BACKUP_PACKAGE_PREFIX
        )
        backup_mod = _allocate_transaction_backup(
            modules_dir, _INSTALL_BACKUP_MOD_PREFIX
        )

        package_existed = _path_exists(destination_package)
        mod_existed = _path_exists(destination_mod)
        previous_mod_text = ""
        if mod_existed:
            try:
                previous_mod_text = destination_mod.read_text(encoding="utf-8-sig")
            except OSError:
                previous_mod_text = ""
        try:
            if package_existed:
                destination_package.rename(backup_package)
                package_moved = True
            if mod_existed:
                destination_mod.rename(backup_mod)
                mod_moved = True

            shutil.copytree(str(staged_package), str(destination_package))
            shutil.copy2(str(staged_mod), str(destination_mod))

            native_backup_sources = list(stale_package_backups)
            if package_moved:
                native_backup_sources.append(backup_package)
            discarded_transient_build_trees = sum(
                1
                for backup_source in native_backup_sources
                if (backup_source / "bifrost" / "out").is_dir()
            )
            _preserve_native_packs_from_backups(
                native_backup_sources, destination_package
            )
            preserved_native_pack = _register_existing_native_pack(
                destination_package,
                destination_mod,
            )
            incompatible_native_pack_preserved = (
                _has_preserved_incompatible_native_pack(destination_package)
                and not preserved_native_pack
            )
            scripts_dir = str(destination_package / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            importlib.invalidate_caches()
            _unload_package()
            package = importlib.import_module("bifrost_scales")
            installed_version = str(getattr(package, "__version__", "unknown"))
            if installed_version != _VERSION:
                raise RuntimeError(
                    "Maya loaded Bifrost Scales {{}} instead of {{}}".format(
                        installed_version, _VERSION
                    )
                )
            version_module = importlib.import_module("bifrost_scales.version")
            if str(getattr(version_module, "VERSION", "")) != _VERSION:
                raise RuntimeError(
                    "Installed bifrost_scales.version does not match the release version"
                )
            if preserved_native_pack and not _mod_registers_native_pack(
                destination_mod, preserved_native_pack
            ):
                raise RuntimeError(
                    "The compatible Native Pack was preserved but BifrostScales.mod does not register its PackConfig"
                )
        except Exception as install_error:
            _unload_package()
            rollback_errors = []
            if package_moved or not package_existed:
                try:
                    _restore(destination_package, backup_package)
                except Exception as rollback_error:
                    rollback_errors.append(
                        "package rollback: {{}}: {{}}".format(
                            type(rollback_error).__name__, rollback_error
                        )
                    )
            if mod_moved or not mod_existed:
                try:
                    _restore(destination_mod, backup_mod)
                except Exception as rollback_error:
                    rollback_errors.append(
                        "module rollback: {{}}: {{}}".format(
                            type(rollback_error).__name__, rollback_error
                        )
                    )
            if rollback_errors:
                raise RuntimeError(
                    "Bifrost Scales install failed and rollback was incomplete. "
                    + " | ".join(rollback_errors)
                ) from install_error
            raise

        cleanup_candidates = list(stale_package_backups) + list(stale_mod_backups)
        if package_moved:
            cleanup_candidates.append(backup_package)
        if mod_moved:
            cleanup_candidates.append(backup_mod)
        for backup in cleanup_candidates:
            if _path_exists(backup) and not _remove_path(backup):
                pending_backup_cleanup.append(str(backup))

        installed_mod_text = ""
        try:
            installed_mod_text = destination_mod.read_text(encoding="utf-8-sig")
        except OSError:
            installed_mod_text = ""
        native_registration_changed = bool(
            preserved_native_pack and installed_mod_text != previous_mod_text
        )

        LAST_INSTALL_REPORT = {{
            "success": True,
            "version": _VERSION,
            "installed_python_version": installed_version,
            "destination": str(destination_package),
            "module_file": str(destination_mod),
            "stale_package_backups_found": len(stale_package_backups),
            "stale_module_backups_found": len(stale_mod_backups),
            "discarded_transient_build_trees": discarded_transient_build_trees,
            "pending_backup_cleanup": tuple(pending_backup_cleanup),
            "restart_required_for_cleanup": bool(pending_backup_cleanup),
            "preserved_native_pack": preserved_native_pack,
            "native_pack_registered": bool(
                preserved_native_pack
                and _mod_registers_native_pack(destination_mod, preserved_native_pack)
            ),
            "native_registration_changed": native_registration_changed,
            "restart_required_for_native_registration": bool(preserved_native_pack),
            "restart_required": bool(pending_backup_cleanup or preserved_native_pack),
        }}

        cleanup_error = ""
        LAST_CLEANUP_REPORT = None
        if remove_legacy:
            try:
                cleanup = importlib.import_module("bifrost_scales.legacy_cleanup")
                report = cleanup.remove_legacy_installations(
                    cmds_module=cmds,
                    include_external=True,
                )
                LAST_CLEANUP_REPORT = report.to_mapping()
            except Exception as exc:
                cleanup_error = "{{}}: {{}}".format(type(exc).__name__, exc)

        if show_tool:
            package.show()

        message = (
            "Bifrost Scales {VERSION}をインストールしました。"
            "\\nNative Bifrost専用Runtimeをインストールしました。"
        )
        if preserved_native_pack:
            message += (
                "\\n互換Native Core 0.10.6 Packを保持し、GraphとManifestを検証してBifrostScales.modへ再登録しました。"
                "\\n追加ビルドは不要ですが、BifrostがPackConfigを読み直すためMayaを完全に再起動してください。"
            )
        elif incompatible_native_pack_preserved:
            message += (
                "\\n旧Native Packは診断用に保持しましたが、Payload Schema 10 / Operator Contract 18 / 0.10.6 Cell Hot Path Contractを満たさないため登録していません。"
                "\\nMayaを完全に終了し、{VERSION}同梱のNative Build Scriptを-Cleanで実行してください。"
            )
        else:
            message += (
                "\\nNative Backendは同梱PowerShellでPackを-Cleanビルド後、"
                "Mayaを再起動してください。"
            )
        if discarded_transient_build_trees:
            message += (
                "\\n旧bifrost/outビルド中間物は長いVisual Studioパスを含むため引き継ぎませんでした。"
                "\\n完成済みNative Packのみ保持しています。必要な場合はMaya終了後に-Cleanビルドしてください。"
            )
        if pending_backup_cleanup:
            message += (
                "\\nMayaが使用中のNative DLLを含む旧インストールバックアップを{{}}件保持しました。"
                "\\nインストール自体は完了しています。Maya再起動後の次回インストール時に自動清掃します。"
            ).format(len(pending_backup_cleanup))
        if LAST_CLEANUP_REPORT is not None:
            message += "\\n旧ツール削除: {{}}件".format(len(LAST_CLEANUP_REPORT.get("removed", ())))
            pending = LAST_CLEANUP_REPORT.get("pending", ())
            if pending:
                message += "\\n保留: {{}}件。Maya終了後にComplete Legacy Cleanupを実行してください。".format(len(pending))
            if LAST_CLEANUP_REPORT.get("restart_required"):
                message += "\\nMayaの再起動が必要です。"
        if cleanup_error:
            message += "\\n旧ツール削除中にエラー: " + cleanup_error
        try:
            cmds.confirmDialog(title="Bifrost Scales", message=message, button=["OK"])
        except Exception:
            print(message)
        return destination_package
    finally:
        shutil.rmtree(str(staging_root), ignore_errors=True)


def onMayaDroppedPythonFile(*_args):
    result = install(show_tool=False)
    if LAST_INSTALL_REPORT is not None:
        print(LAST_INSTALL_REPORT)
    return result


if __name__ == "__main__":
    try:
        import maya.cmds  # type: ignore  # noqa: F401
    except Exception:
        pass
    else:
        install()
'''


def _current_release_prefix() -> str:
    return "BifrostScales_{}".format(VERSION.replace(".", "_"))


def _is_stale_top_level_release_artifact(path: Path) -> bool:
    """Reject versioned artifacts from an older release at ZIP root.

    Historical documentation under ``docs/`` remains available, but generated
    installers, post-install checks, checksum files, and other versioned root
    artifacts from older releases must never be mixed into a new source ZIP.
    """

    if path.parent != ROOT:
        return False
    name = path.name
    return name.startswith("BifrostScales_0_") and not name.startswith(
        _current_release_prefix()
    )


def _is_self_referential_release_report(path: Path) -> bool:
    """Exclude reports whose contents necessarily depend on the final ZIP hash."""

    return path.parent == ROOT and path.name in {
        _current_release_prefix() + "_RELEASE_CONSISTENCY_AUDIT.json",
        _current_release_prefix() + "_FINAL_VERIFY.json",
        _current_release_prefix() + "_DELIVERY_SHA256SUMS.txt",
    }


def _source_paths(installer_path: Path) -> list[tuple[Path, str]]:
    result = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if (
            "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or ".git" in path.parts
            or any(part.startswith("build") for part in path.relative_to(ROOT).parts[:-1])
            or "parity-out" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        if path.name in {SOURCE_ZIP_NAME, SOURCE_ZIP_NAME + ".sha256"}:
            continue
        if _is_stale_top_level_release_artifact(path):
            continue
        if _is_self_referential_release_report(path):
            continue
        result.append((path, path.relative_to(ROOT).as_posix()))
    return result


def _write_checksums() -> None:
    lines = []
    for path in sorted(ROOT.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or ".git" in path.parts
            or any(part.startswith("build") for part in path.relative_to(ROOT).parts[:-1])
            or "parity-out" in path.parts
            or path.suffix == ".pyc"
            or path.name == "SHA256SUMS.txt"
            or _is_stale_top_level_release_artifact(path)
            or _is_self_referential_release_report(path)
        ):
            continue
        relative = path.relative_to(ROOT).as_posix()
        lines.append("{}  {}".format(hashlib.sha256(path.read_bytes()).hexdigest(), relative))
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build() -> dict[str, str]:
    payload = _zip_bytes(_runtime_paths())
    installer = ROOT / INSTALLER_NAME
    installer.write_text(_installer_source(payload), encoding="utf-8", newline="\n")
    build_info = {
        "product": "Bifrost Scales",
        "version": VERSION,
        "schema": "bifrost-scales/5",
        "milestone": "exact-single-site-cell-hot-path",
        "build_date": "2026-08-24",
        "runtime_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "standalone": True,
        "runtime_engine": "native-bifrost-only",
        "generation_compute_backend": "hybrid-opencl-orientation-cpu-exact-indexed-distribution",
        "gpu_generation_compute": True,
        "gpu_stage": "interactive-orientation-with-zero-direction-relax",
        "gpu_buffer_schema": "bifrost-scales/compact-orientation-buffer/1",
        "gpu_environment_policy": "BIFROST_SCALES_GPU=auto|off|force",
        "gpu_default_crossover_samples": 4096,
        "gpu_failure_policy": "automatic-cpu-multicore-fallback",
        "settled_and_final_backend": "deterministic-cpu-multicore",
        "viewport_rendering": "maya-viewport-2-gpu-managed",
        "cpu_thread_environment_override": "BIFROST_SCALES_CPU_THREADS",
        "cpu_thread_automatic_policy": "hardware-concurrency-minus-one-capped-at-32",
        "parallel_stages": ["distribution-relax", "orientation", "direction-relax", "cells", "shape"],
        "exact_worker_count_determinism": True,
        "python_reference_runtime": False,
        "python_reference_preview": False,
        "python_reference_final": False,
        "python_reference_bake": False,
        "removed_python_generation_modules": [
            "adaptive",
            "cells",
            "generator",
            "maya_mesh",
            "maya_smoke",
            "mesh",
            "orientation",
            "relaxation",
            "sampling",
            "surface_features",
        ],
        "create_button_contract": "selected-mesh-to-system-native-graph-and-first-settled-preview",
        "create_transaction_rollback": True,
        "existing_system_missing_graph_policy": "explicit-rebuild-only",
        "final_and_bake_status": "not-exposed-until-native-final-contract",
        "native_core_api": "0.10.6-cell-hot-path-contract",
        "minimum_native_pack": "0.10.6",
        "native_payload_schema": "bifrost-scales/native-payload/10",
        "operator_contract": "bifrost-scales/operator-contract/18",
        "native_behavior_contract": "bifrost-scales/native-core/0.10.6-cell-hot-path-1",
        "native_profile_schema": "bifrost-scales/native-profile/9",
        "cell_cache_key_basis": "distribution-not-orientation",
        "native_stage_cache": "process-shared-bounded-lru-exact-dual-hash",
        "native_stage_cache_default_entries_per_stage": 2,
        "native_stage_cache_environment_override": "BIFROST_SCALES_STAGE_CACHE_ENTRIES=1..8",
        "distribution_candidate_guide_index": "deterministic-authored-order-aabb-bvh",
        "distribution_neighbor_range": "exact-maximum-accepted-spacing-bound",
        "cell_hot_path": "single-site-precomputed-ray-table-normal-component-mask-gate",
        "cell_ray_trigonometry": "shared-precomputed-table",
        "cell_neighbor_normalization": "precomputed",
        "mask_cell_ray_gate": "once-per-cell-build",
        "direction_pair_partition_runtime": False,
        "direction_edits_reuse_exact_cell_partition": True,
        "direction_edit_orientation_policy": "0.10.2-full-rebuild-no-dirty-region",
        "open_boundary_density_adaptive": True,
        "open_boundary_density_spacing": "inverse-sqrt-local-density",
        "static_graph": "Graphs::BifrostScales::native_scales_v4",
        "static_graph_revision": 4,
        "graph_host_contract": "bifrost-scales/native-graph/4-dgmesh-1",
        "native_mesh_binding": "maya-dg-worldMesh",
        "normal_updates": ["payload_json", "parent_visibility"],
        "runtime_topology_mutation": False,
        "target_reconnect_on_normal_update": False,
        "preserve_existing_native_pack_on_update": True,
        "reuse_exact_0_10_5_pack_without_rebuild": False,
        "native_pack_rebuild_required_for_release": True,
        "mesh_free_cell_picker": True,
        "cell_picker_overlay_submission_owner": "drawFeedback-only",
        "cell_picker_stale_highlight_lifecycle_fix": True,
        "stable_cell_id_schema": "bifrost-scales/cell-id/1",
        "cell_metadata_schema": "bifrost-scales/cell-metadata/1",
        "unique_scale_registration": True,
        "unique_scale_override_schema": "bifrost-scales/unique-overrides/1",
        "unique_scale_override_authoring": True,
        "unique_scale_override_native_application": False,
        "guide_groups": True,
        "guide_symmetry": True,
        "guide_mask_effect": True,
        "scale_type_selection_mode": "strongest-positive-guide-or-group-link",
        "uv_boundary_feature": "removed",
        "preview_scale_limit": 50000,
        "installer_transaction_backup_mode": "unique-per-install",
        "installer_locked_native_dll_cleanup_deferred": True,
        "installer_mod_registers_preserved_native_pack": True,
        "installer_native_preservation_scope": "installed-pack-only",
        "installer_discards_transient_bifrost_out": True,
        "installer_revision": 2,
        "source_zip_excludes_stale_top_level_release_artifacts": True,
        "release_consistency_audit_schema": "bifrost-scales/release-consistency-audit/2",
        "native_only_runtime_audit_schema": "bifrost-scales/native-only-runtime-audit/1",
    }
    (ROOT / "BUILD_INFO.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_checksums()
    source_zip = ROOT.parent / SOURCE_ZIP_NAME
    source_zip.write_bytes(_zip_bytes(_source_paths(installer)))
    public_installer = ROOT.parent / INSTALLER_NAME
    public_installer.write_bytes(installer.read_bytes())
    installer_digest = hashlib.sha256(public_installer.read_bytes()).hexdigest()
    source_digest = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    (ROOT.parent / (INSTALLER_NAME + ".sha256")).write_text(
        "{}  {}\n".format(installer_digest, INSTALLER_NAME),
        encoding="utf-8",
    )
    (ROOT.parent / (SOURCE_ZIP_NAME + ".sha256")).write_text(
        "{}  {}\n".format(source_digest, SOURCE_ZIP_NAME),
        encoding="utf-8",
    )
    return {
        "installer": str(public_installer),
        "installer_sha256": installer_digest,
        "source_zip": str(source_zip),
        "source_zip_sha256": source_digest,
        "payload_sha256": build_info["runtime_payload_sha256"],
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
