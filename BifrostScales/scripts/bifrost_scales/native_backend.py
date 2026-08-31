"""Native Bifrost preview host boundary.

This module deliberately does not edit VNN topology at runtime. A pre-published
static graph is imported as a shape, Maya's evaluated ``worldMesh[0]`` output is
connected once to the graph's published ``source_mesh`` attribute, and normal
updates write only ``payload_json`` and the ordinary parent transform visibility.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .guides import GuideSet
from .native_payload import NATIVE_PAYLOAD_SCHEMA, build_native_payload
from .scene import SystemBinding
from .settings import ScaleSettings

GRAPH_DEFINITION = "Graphs::BifrostScales::native_scales_v4"
OPERATOR_NAMESPACE = "BifrostScales"
OPERATOR_SHORT_NAME = "generate_scale_mesh_payload_arrays"
OPERATOR_DEFINITION = "{}::{}".format(OPERATOR_NAMESPACE, OPERATOR_SHORT_NAME)
GRAPH_ASSET_NAME = "BifrostScales_native_scales_v4_graph.json"
GRAPH_CONTRACT = "bifrost-scales/native-graph/4-dgmesh-1"
PACK_CONFIG_NAME = "BifrostScalesPackConfig.json"
MANIFEST_NAME = "manifest.bifrost-scales.json"
MINIMUM_NATIVE_PACK_VERSION = (0, 10, 9)
MINIMUM_NATIVE_PACK_VERSION_TEXT = "0.10.9"
NATIVE_BEHAVIOR_CONTRACT = "bifrost-scales/native-core/0.10.9-settled-proposal-index-1"
NATIVE_PROFILE_SCHEMA = "bifrost-scales/native-profile/11"

NATIVE_GRAPH_PATH_ATTR = "bsNativeGraphPath"
NATIVE_GRAPH_UUID_ATTR = "bsNativeGraphUuid"
NATIVE_GRAPH_OWNER_ATTR = "bsOwnedNativeGraph"
NATIVE_GRAPH_SYSTEM_ATTR = "bsNativeGraphSystemId"
NATIVE_GRAPH_OPERATOR_ATTR = "bsNativeGraphOperatorDefinition"
NATIVE_GRAPH_CONTRACT_ATTR = "bsNativeGraphContract"
NATIVE_GRAPH_TARGET_PATH_ATTR = "bsNativeGraphTargetPath"
NATIVE_GRAPH_TARGET_UUID_ATTR = "bsNativeGraphTargetUuid"
NATIVE_GRAPH_INPUT_TYPE_ATTR = "bsNativeGraphInputSuggestedType"
NATIVE_GRAPH_SOURCE_PLUG_ATTR = "bsNativeGraphSourcePlug"
NATIVE_GRAPH_BINDING_MODE_ATTR = "bsNativeGraphBindingMode"
NATIVE_GRAPH_ASYNC_POLICY_ATTR = "bsNativeGraphAsyncPolicy"
NATIVE_GRAPH_EVALUATION_POLICY_ATTR = "bsNativeGraphEvaluationPolicy"

DEFAULT_NATIVE_EVALUATION_TIMEOUT_SECONDS = 30.0
DEFAULT_NATIVE_EVALUATION_POLL_SECONDS = 0.01

_REQUIRED_GRAPH_ATTRIBUTES = (
    "payload_json",
    "success",
    "status",
    "scale_count",
    "point_count",
    "face_count",
)

_TRANSIENT_SOURCE_STATUSES = frozenset(
    {
        "source mesh has no positions",
        "source mesh has no face topology",
        "source mesh arrays are not connected",
    }
)


_REQUIRED_MESH_TOPOLOGY_PORT_TYPES = {
    "source_face_offset": "array<uint>",
    "source_face_vertex": "array<uint>",
    "face_offset": "array<uint>",
    "face_vertex": "array<uint>",
}


@dataclass(frozen=True)
class NativeBackendStatus:
    module_root: str
    graph_asset: str
    pack_config: str
    operator_binary: str
    nodedef_json: str
    graph_asset_available: bool
    pack_config_available: bool
    pack_config_registered: bool
    pack_config_active: bool
    definition_library_registered: bool
    operator_binary_available: bool
    nodedef_available: bool
    bifrost_command_available: bool
    catalog_query_available: bool
    operator_definition_available: bool
    catalog_match: str
    restart_required: bool
    ready: bool
    reasons: tuple[str, ...]
    graph_library_registered: bool = False
    pack_resources_isolated: bool = False
    catalog_runtime: str = ""
    catalog_library: str = ""
    catalog_error: str = ""
    catalog_runtimes: tuple[str, ...] = ()
    resolved_operator_definition: str = ""
    catalog_namespace_exact: bool = False
    catalog_namespace_duplicated: bool = False
    rebuild_required: bool = False
    mesh_topology_contract_valid: bool = False
    graph_input_contract_valid: bool = False
    nodedef_port_types: tuple[tuple[str, str], ...] = ()
    pack_version: str = ""
    minimum_pack_version: str = MINIMUM_NATIVE_PACK_VERSION_TEXT
    native_behavior_contract_valid: bool = False
    native_behavior_contract_expected: str = NATIVE_BEHAVIOR_CONTRACT
    module_native_behavior_contract: str = ""
    pack_native_behavior_contract: str = ""
    payload_schema_expected: str = NATIVE_PAYLOAD_SCHEMA
    module_graph_payload_schema: str = ""
    module_manifest_payload_schema: str = ""
    pack_graph_payload_schema: str = ""
    pack_manifest_payload_schema: str = ""
    payload_schema_contract_valid: bool = False
    native_profile_schema_expected: str = NATIVE_PROFILE_SCHEMA
    module_manifest_profile_schema: str = ""
    pack_manifest_profile_schema: str = ""
    native_profile_schema_contract_valid: bool = False
    profile_output_contract_valid: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NativeGraphEvaluation:
    graph_shape: str
    graph_parent: str
    success: bool
    status: str
    scale_count: int
    point_count: int
    face_count: int
    payload_changed: bool
    generation_ms: float
    viewport_ms: float
    total_ms: float
    execution_wait_ms: float = 0.0
    execution_counter_before: int = -1
    execution_counter_after: int = -1
    evaluation_policy: str = ""
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _NativeOutputSnapshot:
    success: bool
    status: str
    scale_count: int
    point_count: int
    face_count: int
    profile_json: str = ""

    def fingerprint(self) -> tuple[bool, str, int, int, int]:
        return (
            self.success,
            self.status,
            self.scale_count,
            self.point_count,
            self.face_count,
        )


@dataclass(frozen=True)
class _NativeExecutionWait:
    snapshot: _NativeOutputSnapshot
    waited_ms: float
    counter_before: int
    counter_after: int
    policy: str


def _parse_native_profile(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict) or value.get("schema") != NATIVE_PROFILE_SCHEMA:
        return {}
    return value


def _module_root() -> Path:
    # .../BifrostScales/scripts/bifrost_scales/native_backend.py
    return Path(__file__).resolve().parents[2]


def _first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _registered_pack_configs(module_root: Path) -> tuple[Path, ...]:
    """Read PackConfig registrations from the Maya module file.

    The 0.6.0 build assumed that Bifrost left ``CMAKE_INSTALL_PREFIX``
    untouched. Bifrost 2.15 instead installs into a versioned child such as
    ``bifrost/pack/BifrostScalesCore-0.6.x``. The module file is therefore the
    authoritative location after a successful build.
    """

    mod_file = module_root.parent / "BifrostScales.mod"
    if not mod_file.is_file():
        return ()
    try:
        lines = mod_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except OSError:
        return ()

    result: list[Path] = []
    pattern = re.compile(
        r"^\s*BIFROST_LIB_CONFIG_FILES\s*(\+?[:]?=)\s*(.*?)\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        operator, raw_value = match.groups()
        value = raw_value.strip().strip('\"').strip("'")
        if not value:
            continue
        candidate = Path(os.path.expandvars(os.path.expanduser(value)))
        if not candidate.is_absolute() or operator == "+:=":
            candidate = module_root / candidate
        result.append(candidate)
    return tuple(result)


def _pack_config_candidates(module_root: Path) -> tuple[Path, ...]:
    pack_container = module_root / "bifrost" / "pack"
    ordered: list[Path] = list(_registered_pack_configs(module_root))
    ordered.append(pack_container / PACK_CONFIG_NAME)
    if pack_container.exists():
        nested = sorted(
            pack_container.rglob(PACK_CONFIG_NAME),
            key=lambda item: (
                item.parent.name,
                item.as_posix(),
            ),
            reverse=True,
        )
        ordered.extend(nested)

    seen: set[str] = set()
    result: list[Path] = []
    for candidate in ordered:
        key = _normalized_path(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return tuple(result)


def _native_pack_version(pack_config: Path) -> tuple[int, int, int]:
    """Read the semantic Native Core version from PackConfig or its directory."""

    values: list[str] = []
    if pack_config.is_file():
        try:
            data = json.loads(pack_config.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            data = {}
        for configuration in data.get("AminoConfigurations", ()):
            if isinstance(configuration, dict):
                values.append(str(configuration.get("libraryVersion", "") or ""))
    values.append(pack_config.parent.name.rsplit("-", 1)[-1])
    for value in values:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
        if match:
            return tuple(int(part) for part in match.groups())
    return ()


def _native_pack_version_text(pack_config: Path) -> str:
    version = _native_pack_version(pack_config)
    return ".".join(str(part) for part in version) if version else "unknown"


def _native_behavior_contract_valid(pack_config: Path) -> bool:
    if _native_pack_version(pack_config) < MINIMUM_NATIVE_PACK_VERSION:
        return False
    manifest = pack_config.parent / "metadata" / MANIFEST_NAME
    return _manifest_behavior_contract(manifest) == NATIVE_BEHAVIOR_CONTRACT


def _process_pack_configs(environ: Any | None = None) -> tuple[Path, ...]:
    """Return PackConfig paths visible to the current Maya process.

    Updating a module file inside a running Maya session does not update the
    process environment or the already-loaded Bifrost node catalog. File-only
    checks would therefore incorrectly report the Native Backend as ready.
    """

    environment = os.environ if environ is None else environ
    raw = str(environment.get("BIFROST_LIB_CONFIG_FILES", "") or "").strip()
    if not raw:
        return ()
    separator = ";" if ";" in raw else os.pathsep
    result: list[Path] = []
    for value in raw.split(separator):
        candidate = value.strip().strip('"').strip("'")
        if candidate:
            result.append(Path(os.path.expandvars(os.path.expanduser(candidate))))
    return tuple(result)


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),)


@dataclass(frozen=True)
class _CatalogProbeResult:
    query_available: bool
    definition_available: bool
    match: str
    runtime: str
    library: str
    error: str
    runtimes: tuple[str, ...]
    resolved_definition: str = ""
    namespace_exact: bool = False
    namespace_duplicated: bool = False


def _catalog_node_tail(value: str) -> str:
    parts = [item for item in re.split(r"::|,|/", str(value)) if item]
    return parts[-1] if parts else ""


def _resolved_catalog_definition(library: str, node: str) -> str:
    """Build the graph node type represented by one raw VNN catalog entry."""

    tail = _catalog_node_tail(node)
    if tail != OPERATOR_SHORT_NAME:
        return ""
    if str(library) == OPERATOR_NAMESPACE:
        return OPERATOR_DEFINITION
    return "{}::{}".format(str(library), tail) if library else tail


def _operator_catalog_probe(cmds_module: Any | None) -> _CatalogProbeResult:
    """Query the raw VNN catalog and require the exact public namespace.

    VNN lists nodes *inside* a library.  A short-name match is therefore not
    enough: the 0.6.0--0.6.4 header annotation accidentally registered this
    operator in ``BifrostScales::BifrostScales`` while the static graph
    referenced ``BifrostScales::...``.  The old fuzzy probe reported that
    incompatible catalog entry as ready.
    """

    if cmds_module is None or not hasattr(cmds_module, "vnn"):
        return _CatalogProbeResult(
            False,
            False,
            "",
            "",
            "",
            "maya.cmds.vnn is unavailable",
            (),
        )

    errors: list[str] = []
    discovered: tuple[str, ...] = ()
    try:
        discovered = _as_string_tuple(cmds_module.vnn(runTimes=1))
    except Exception as exc:
        errors.append("runTimes: {}: {}".format(type(exc).__name__, exc))

    ordered: list[str] = []
    for runtime in sorted(
        discovered,
        key=lambda item: ("bifrost" not in item.lower(), item.lower()),
    ) + ["BifrostGraph", "Bifrost"]:
        if runtime and runtime not in ordered:
            ordered.append(runtime)

    any_success = False
    incompatible: _CatalogProbeResult | None = None
    for runtime in ordered:
        try:
            libraries = _as_string_tuple(cmds_module.vnn(libraries=runtime))
            any_success = True
        except Exception as exc:
            errors.append(
                "libraries({}): {}: {}".format(runtime, type(exc).__name__, exc)
            )
            continue

        for library in libraries:
            nodes: tuple[str, ...] = ()
            node_error: Exception | None = None
            for node_args in ([runtime, library], (runtime, library)):
                try:
                    nodes = _as_string_tuple(cmds_module.vnn(nodes=node_args))
                    any_success = True
                    node_error = None
                    break
                except Exception as exc:
                    node_error = exc
            if node_error is not None:
                errors.append(
                    "nodes({}, {}): {}: {}".format(
                        runtime,
                        library,
                        type(node_error).__name__,
                        node_error,
                    )
                )
                continue

            for node in nodes:
                candidate = str(node)
                if _catalog_node_tail(candidate) != OPERATOR_SHORT_NAME:
                    continue
                resolved = _resolved_catalog_definition(str(library), candidate)
                exact = str(library) == OPERATOR_NAMESPACE and (
                    resolved == OPERATOR_DEFINITION
                )
                duplicated = str(library) == "{}::{}".format(
                    OPERATOR_NAMESPACE, OPERATOR_NAMESPACE
                )
                result = _CatalogProbeResult(
                    True,
                    exact,
                    candidate,
                    runtime,
                    str(library),
                    " | ".join(errors),
                    discovered,
                    resolved_definition=resolved,
                    namespace_exact=exact,
                    namespace_duplicated=duplicated,
                )
                if exact:
                    return result
                if incompatible is None or duplicated:
                    incompatible = result

    if incompatible is not None:
        return incompatible
    return _CatalogProbeResult(
        any_success,
        False,
        "",
        "",
        "",
        " | ".join(errors),
        discovered,
    )


def _json_library_registered(
    pack_config: Path,
    resource: Path | None,
) -> bool:
    """Return whether a JSON resource is explicitly registered by PackConfig."""

    if resource is None or not pack_config.is_file():
        return False
    try:
        data = json.loads(pack_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    target = _normalized_path(resource.parent)
    for configuration in data.get("AminoConfigurations", ()):
        if not isinstance(configuration, dict):
            continue
        for library in configuration.get("jsonLibs", ()):
            if not isinstance(library, dict):
                continue
            raw_path = str(library.get("path", "") or "").strip()
            if not raw_path:
                continue
            library_root = Path(raw_path)
            if not library_root.is_absolute():
                library_root = pack_config.parent / library_root
            if _normalized_path(library_root) != target:
                continue
            files = library.get("files", ())
            if isinstance(files, list) and resource.name in {str(item) for item in files}:
                return True
    return False


def _pack_resources_isolated(
    pack_root: Path,
    nodedef: Path | None,
    graph_definition: Path | None,
) -> bool:
    """Ensure only Bifrost definitions live in explicitly scanned folders."""

    if nodedef is None or graph_definition is None:
        return False
    expected_operator_parent = pack_root / "json" / "BifrostScales" / "operators"
    expected_graph_parent = pack_root / "json" / "BifrostScales" / "graphs"
    if _normalized_path(nodedef.parent) != _normalized_path(expected_operator_parent):
        return False
    if _normalized_path(graph_definition.parent) != _normalized_path(expected_graph_parent):
        return False
    legacy_root = pack_root / "json" / "BifrostScales"
    forbidden = (
        legacy_root / "bifrost_scales_nodedef.json",
        legacy_root / GRAPH_ASSET_NAME,
        legacy_root / "manifest.bifrost-scales.json",
    )
    return not any(path.exists() for path in forbidden)


def _definition_library_registered(pack_config: Path, nodedef: Path | None) -> bool:
    return _json_library_registered(pack_config, nodedef)


def _operator_candidates(pack_root: Path) -> tuple[Path, ...]:
    names = (
        "BifrostScalesOps.dll",
        "libBifrostScalesOps.so",
        "libBifrostScalesOps.dylib",
    )
    roots = (pack_root / "lib", pack_root / "bin")
    return tuple(root / name for root in roots for name in names)


def _nodedef_candidates(pack_root: Path) -> tuple[Path, ...]:
    if not pack_root.exists():
        return ()
    result: list[Path] = []
    for path in sorted((pack_root / "json").rglob("*.json")) if (pack_root / "json").exists() else []:
        if path.name == GRAPH_ASSET_NAME:
            continue
        try:
            if OPERATOR_DEFINITION in path.read_text(encoding="utf-8", errors="ignore"):
                result.append(path)
        except OSError:
            continue
    return tuple(result)


def _nodedef_operator_port_types(nodedef: Path | None) -> dict[str, str]:
    """Read the exact generated operator port contract from nodedef JSON."""

    if nodedef is None or not nodedef.is_file():
        return {}
    try:
        data = json.loads(nodedef.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    operators = data.get("operators", ()) if isinstance(data, dict) else ()
    for operator in operators:
        if not isinstance(operator, dict):
            continue
        if str(operator.get("name", "")) != OPERATOR_DEFINITION:
            continue
        result: dict[str, str] = {}
        for port in operator.get("ports", ()):
            if not isinstance(port, dict):
                continue
            name = str(port.get("portName", "") or "")
            port_type = str(port.get("portType", "") or "")
            if name:
                result[name] = port_type
        return result
    return {}


def _mesh_topology_contract_valid(port_types: dict[str, str]) -> bool:
    return all(
        port_types.get(name) == expected
        for name, expected in _REQUIRED_MESH_TOPOLOGY_PORT_TYPES.items()
    )


def _graph_input_contract_valid(graph_definition: Path | None) -> bool:
    """Validate the immutable top-level Object mesh-input graph contract.

    Maya supplies polygon data through a real DG connection from
    ``meshShape.worldMesh[0]`` to the imported ``bifrostGraphShape.source_mesh``
    attribute.  The serialized graph still retains typed path metadata for
    compatibility and inspection, but that metadata is not treated as proof of
    an active mesh-data connection.
    """

    if graph_definition is None or not graph_definition.is_file():
        return False
    try:
        data = json.loads(graph_definition.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    compounds = data.get("compounds", ()) if isinstance(data, dict) else ()
    if not isinstance(compounds, list) or len(compounds) != 1:
        return False
    compound = compounds[0]
    if not isinstance(compound, dict):
        return False
    if str(compound.get("name", "")) != GRAPH_DEFINITION:
        return False

    metadata = compound.get("metadata", ())
    graph_marker = next(
        (
            entry
            for entry in metadata
            if isinstance(entry, dict) and entry.get("metaName") == "compoundIsGraph"
        ),
        None,
    )
    if not isinstance(graph_marker, dict) or str(graph_marker.get("metaValue", "")).lower() != "true":
        return False

    source_port = next(
        (
            port
            for port in compound.get("ports", ())
            if isinstance(port, dict) and port.get("portName") == "source_mesh"
        ),
        None,
    )
    if not isinstance(source_port, dict) or source_port.get("portType") != "Object":
        return False
    pathinfo = next(
        (
            entry
            for entry in source_port.get("metadata", ())
            if isinstance(entry, dict) and entry.get("metaName") == "pathinfo"
        ),
        None,
    )
    if not isinstance(pathinfo, dict):
        return False
    leaves = {
        str(entry.get("metaName", "")): entry
        for entry in pathinfo.get("metadata", ())
        if isinstance(entry, dict)
    }
    for name in ("path", "setOperation", "active"):
        entry = leaves.get(name)
        if not isinstance(entry, dict) or entry.get("metaType") != "string":
            return False
    if str(leaves["active"].get("metaValue", "")).lower() != "true":
        return False
    if str(leaves["setOperation"].get("metaValue", "")) != "+":
        return False

    connections = {
        (str(item.get("source", "")), str(item.get("target", "")))
        for item in compound.get("connections", ())
        if isinstance(item, dict)
    }
    return (".source_mesh", "get_mesh_structure.mesh") in connections



def _graph_payload_schema(graph_definition: Path | None) -> str:
    """Return the payload schema encoded in a Published Graph input default."""

    if graph_definition is None or not graph_definition.is_file():
        return ""
    try:
        data = json.loads(graph_definition.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    compounds = data.get("compounds", ()) if isinstance(data, dict) else ()
    if not isinstance(compounds, list) or len(compounds) != 1:
        return ""
    compound = compounds[0]
    if not isinstance(compound, dict):
        return ""
    payload_port = next(
        (
            port
            for port in compound.get("ports", ())
            if isinstance(port, dict) and port.get("portName") == "payload_json"
        ),
        None,
    )
    if not isinstance(payload_port, dict):
        return ""
    default = payload_port.get("portDefault")
    if isinstance(default, dict):
        payload = default
    else:
        try:
            payload = json.loads(str(default or ""))
        except (ValueError, TypeError):
            return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("schema", "") or "")


def _manifest_payload_schema(manifest: Path | None) -> str:
    if manifest is None or not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("native_payload_schema", "") or "")


def _manifest_behavior_contract(manifest: Path | None) -> str:
    if manifest is None or not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("native_behavior_contract", "") or "")


def _manifest_profile_schema(manifest: Path | None) -> str:
    if manifest is None or not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("native_profile_schema", "") or "")


def _pack_manifest_candidates(pack_root: Path) -> tuple[Path, ...]:
    preferred = pack_root / "metadata" / MANIFEST_NAME
    result = [preferred]
    if pack_root.exists():
        result.extend(sorted(pack_root.rglob(MANIFEST_NAME)))
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in result:
        key = _normalized_path(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return tuple(unique)

def _pack_graph_candidates(pack_root: Path) -> tuple[Path, ...]:
    json_root = pack_root / "json"
    if not json_root.exists():
        return ()
    return tuple(sorted(json_root.rglob(GRAPH_ASSET_NAME)))


def probe_native_backend(
    cmds_module: Any | None = None,
    environ: Any | None = None,
) -> NativeBackendStatus:
    """Inspect files, process registration, and the live Bifrost node catalog."""

    module_root = _module_root()
    graph_asset = module_root / "bifrost" / "compounds" / GRAPH_ASSET_NAME
    registered_configs = _registered_pack_configs(module_root)
    registered_keys = {_normalized_path(path) for path in registered_configs}
    process_configs = _process_pack_configs(environ)
    process_keys = {_normalized_path(path) for path in process_configs}
    config_candidates = _pack_config_candidates(module_root)
    pack_config = _first_existing(config_candidates)
    if pack_config is None:
        pack_config = module_root / "bifrost" / "pack" / PACK_CONFIG_NAME
    pack_root = pack_config.parent
    pack_version = _native_pack_version_text(pack_config)
    native_behavior_contract_valid = _native_behavior_contract_valid(pack_config)
    pack_key = _normalized_path(pack_config)
    pack_config_registered = pack_key in registered_keys
    pack_config_active = pack_key in process_keys
    operator = _first_existing(_operator_candidates(pack_root))
    nodedef = _first_existing(_nodedef_candidates(pack_root))
    nodedef_port_types = _nodedef_operator_port_types(nodedef)
    mesh_topology_contract_valid = _mesh_topology_contract_valid(nodedef_port_types)
    profile_output_contract_valid = nodedef_port_types.get("profile_json") == "string"
    pack_graph = _first_existing(_pack_graph_candidates(pack_root))
    module_manifest = module_root / "bifrost" / "compounds" / MANIFEST_NAME
    pack_manifest = _first_existing(_pack_manifest_candidates(pack_root))
    module_graph_payload_schema = _graph_payload_schema(graph_asset)
    module_manifest_payload_schema = _manifest_payload_schema(module_manifest)
    pack_graph_payload_schema = _graph_payload_schema(pack_graph)
    pack_manifest_payload_schema = _manifest_payload_schema(pack_manifest)
    module_native_behavior_contract = _manifest_behavior_contract(module_manifest)
    pack_native_behavior_contract = _manifest_behavior_contract(pack_manifest)
    module_manifest_profile_schema = _manifest_profile_schema(module_manifest)
    pack_manifest_profile_schema = _manifest_profile_schema(pack_manifest)
    native_profile_schema_contract_valid = all(
        value == NATIVE_PROFILE_SCHEMA
        for value in (
            module_manifest_profile_schema,
            pack_manifest_profile_schema,
        )
    )
    payload_schema_contract_valid = all(
        value == NATIVE_PAYLOAD_SCHEMA
        for value in (
            module_graph_payload_schema,
            module_manifest_payload_schema,
            pack_graph_payload_schema,
            pack_manifest_payload_schema,
        )
    )
    module_graph_input_contract_valid = _graph_input_contract_valid(graph_asset)
    pack_graph_input_contract_valid = _graph_input_contract_valid(pack_graph)
    graph_input_contract_valid = (
        module_graph_input_contract_valid and pack_graph_input_contract_valid
    )
    definition_library_registered = _definition_library_registered(pack_config, nodedef)
    graph_library_registered = _json_library_registered(pack_config, pack_graph)
    pack_resources_isolated = _pack_resources_isolated(pack_root, nodedef, pack_graph)

    if cmds_module is None:
        try:
            import maya.cmds as cmds_module  # type: ignore
        except Exception:
            cmds_module = None
    command_available = bool(cmds_module is not None and hasattr(cmds_module, "bifrostGraph"))
    catalog = _operator_catalog_probe(cmds_module)
    catalog_query_available = catalog.query_available
    operator_definition_available = catalog.definition_available
    catalog_match = catalog.match
    catalog_error = catalog.error
    resolved_operator_definition = catalog.resolved_definition
    catalog_namespace_exact = catalog.namespace_exact
    catalog_namespace_duplicated = catalog.namespace_duplicated

    reasons: list[str] = []
    restart_required = False
    rebuild_required = False
    if not graph_asset.is_file():
        reasons.append("static Published Graph asset is missing")
    elif not module_graph_input_contract_valid:
        reasons.append(
            "module Published Graph is missing the typed top-level Object mesh "
            "input contract (compoundIsGraph + source_mesh -> get_mesh_structure)"
        )
    elif module_graph_payload_schema != NATIVE_PAYLOAD_SCHEMA:
        reasons.append(
            "module Published Graph payload schema is {} but Python requires {}".format(
                module_graph_payload_schema or "missing",
                NATIVE_PAYLOAD_SCHEMA,
            )
        )
    if module_manifest_payload_schema != NATIVE_PAYLOAD_SCHEMA:
        reasons.append(
            "module manifest payload schema is {} but Python requires {}".format(
                module_manifest_payload_schema or "missing",
                NATIVE_PAYLOAD_SCHEMA,
            )
        )
    if module_native_behavior_contract != NATIVE_BEHAVIOR_CONTRACT:
        reasons.append(
            "module manifest behavior contract is {} but Python requires {}".format(
                module_native_behavior_contract or "missing",
                NATIVE_BEHAVIOR_CONTRACT,
            )
        )
    if module_manifest_profile_schema != NATIVE_PROFILE_SCHEMA:
        reasons.append(
            "module manifest profile schema is {} but Python requires {}".format(
                module_manifest_profile_schema or "missing",
                NATIVE_PROFILE_SCHEMA,
            )
        )
    if not pack_config.is_file():
        reasons.append("native PackConfig has not been built")
    elif _native_pack_version(pack_config) < MINIMUM_NATIVE_PACK_VERSION:
        rebuild_required = True
        reasons.append(
            "Native Pack {} is older than the required {} behavior contract. "
            "Rebuild the 0.10.9 Native Pack with -Clean and completely restart Maya.".format(
                pack_version, MINIMUM_NATIVE_PACK_VERSION_TEXT
            )
        )
    elif not native_behavior_contract_valid:
        rebuild_required = True
        reasons.append(
            "Native Pack behavior contract is {} but Python requires {}. "
            "Payload Schema 10 / Operator Contract 20 alone cannot prove the 0.10.9 distribution and cache "
            "behavior; "
            "rebuild the 0.10.9 Native Pack with -Clean and "
            "completely restart Maya.".format(
                pack_native_behavior_contract or "missing",
                NATIVE_BEHAVIOR_CONTRACT,
            )
        )
    elif not pack_config_registered:
        reasons.append("native PackConfig is not registered in BifrostScales.mod")
    elif not pack_config_active:
        restart_required = True
        reasons.append(
            "Maya restart required: the current process BIFROST_LIB_CONFIG_FILES "
            "does not include the native PackConfig"
        )
    if operator is None:
        reasons.append("native operator binary has not been built")
    if nodedef is None:
        reasons.append("generated Bifrost node definition is missing")
    elif not definition_library_registered:
        reasons.append(
            "native PackConfig does not explicitly register "
            "./json/BifrostScales/operators/bifrost_scales_nodedef.json"
        )
    elif not mesh_topology_contract_valid:
        rebuild_required = True
        reasons.append(
            "Native Operator mesh topology ports are incompatible with "
            "Geometry::Mesh::construct_mesh. source_face_offset, "
            "source_face_vertex, face_offset, and face_vertex must all be "
            "array<uint>. Rebuild the 0.10.9 Native Pack with -Clean."
        )
    elif not profile_output_contract_valid:
        rebuild_required = True
        reasons.append(
            "Native Operator Contract 20 requires a string profile_json output. "
            "Rebuild the 0.10.9 Native Pack with -Clean."
        )
    if pack_graph is None:
        reasons.append("static graph definition is missing from the native pack")
    elif not graph_library_registered:
        reasons.append(
            "native PackConfig does not explicitly register "
            "./json/BifrostScales/graphs/BifrostScales_native_scales_v4_graph.json"
        )
    elif not pack_graph_input_contract_valid:
        rebuild_required = True
        reasons.append(
            "Native Pack graph does not expose the required top-level Object "
            "source_mesh input wired to get_mesh_structure. Reinstall Bifrost Scales 0.10.9 or "
            "rebuild the compatible 0.10.9 Native Core Pack."
        )
    elif pack_graph_payload_schema != NATIVE_PAYLOAD_SCHEMA:
        rebuild_required = True
        reasons.append(
            "Native Pack graph payload schema is {} but Python requires {}. "
            "Reinstall Bifrost Scales 0.10.9; if the mismatch remains, rebuild the "
            "0.10.9 Native Pack with -Clean and restart Maya.".format(
                pack_graph_payload_schema or "missing",
                NATIVE_PAYLOAD_SCHEMA,
            )
        )
    if pack_config.is_file() and pack_manifest_payload_schema != NATIVE_PAYLOAD_SCHEMA:
        rebuild_required = True
        reasons.append(
            "Native Pack manifest payload schema is {} but Python requires {}. "
            "The operator DLL and graph cannot be treated as compatible by version alone.".format(
                pack_manifest_payload_schema or "missing",
                NATIVE_PAYLOAD_SCHEMA,
            )
        )
    if pack_config.is_file() and pack_manifest_profile_schema != NATIVE_PROFILE_SCHEMA:
        rebuild_required = True
        reasons.append(
            "Native Pack manifest profile schema is {} but Python requires {}. "
            "Rebuild the 0.10.9 Native Pack with -Clean.".format(
                pack_manifest_profile_schema or "missing",
                NATIVE_PROFILE_SCHEMA,
            )
        )
    if not pack_resources_isolated:
        reasons.append(
            "native JSON resources are not isolated: operator definitions, graphs, "
            "and non-Bifrost metadata must not share one scanned jsonLib directory"
        )
    if not command_available:
        reasons.append("maya.cmds.bifrostGraph is unavailable")
    if pack_config_active:
        if not catalog_query_available:
            reasons.append("maya.cmds.vnn node-catalog query is unavailable")
        elif catalog_namespace_duplicated:
            rebuild_required = True
            restart_required = True
            reasons.append(
                "The loaded operator uses the invalid doubled namespace {}. "
                "Reinstall Bifrost Scales 0.10.9, rebuild the Native Pack with -Clean, then "
                "completely restart Maya.".format(resolved_operator_definition)
            )
        elif not operator_definition_available:
            restart_required = True
            detail = " ({})".format(catalog_error) if catalog_error else ""
            reasons.append(
                "Native Pack is active but Bifrost's current node catalog does not "
                "contain the exact definition {}{}. Rebuild the compatible 0.10.9 core pack, then "
                "completely restart Maya.".format(OPERATOR_DEFINITION, detail)
            )

    return NativeBackendStatus(
        module_root=str(module_root),
        graph_asset=str(graph_asset),
        pack_config=str(pack_config),
        operator_binary=str(operator or ""),
        nodedef_json=str(nodedef or ""),
        graph_asset_available=graph_asset.is_file(),
        pack_config_available=pack_config.is_file(),
        pack_config_registered=pack_config_registered,
        pack_config_active=pack_config_active,
        definition_library_registered=definition_library_registered,
        operator_binary_available=operator is not None,
        nodedef_available=nodedef is not None,
        bifrost_command_available=command_available,
        catalog_query_available=catalog_query_available,
        operator_definition_available=operator_definition_available,
        catalog_match=catalog_match,
        restart_required=restart_required,
        ready=not reasons,
        reasons=tuple(reasons),
        graph_library_registered=graph_library_registered,
        pack_resources_isolated=pack_resources_isolated,
        catalog_runtime=catalog.runtime,
        catalog_library=catalog.library,
        catalog_error=catalog.error,
        catalog_runtimes=catalog.runtimes,
        resolved_operator_definition=resolved_operator_definition,
        catalog_namespace_exact=catalog_namespace_exact,
        catalog_namespace_duplicated=catalog_namespace_duplicated,
        rebuild_required=rebuild_required,
        mesh_topology_contract_valid=mesh_topology_contract_valid,
        graph_input_contract_valid=graph_input_contract_valid,
        nodedef_port_types=tuple(sorted(nodedef_port_types.items())),
        pack_version=pack_version,
        minimum_pack_version=MINIMUM_NATIVE_PACK_VERSION_TEXT,
        native_behavior_contract_valid=native_behavior_contract_valid,
        native_behavior_contract_expected=NATIVE_BEHAVIOR_CONTRACT,
        module_native_behavior_contract=module_native_behavior_contract,
        pack_native_behavior_contract=pack_native_behavior_contract,
        payload_schema_expected=NATIVE_PAYLOAD_SCHEMA,
        module_graph_payload_schema=module_graph_payload_schema,
        module_manifest_payload_schema=module_manifest_payload_schema,
        pack_graph_payload_schema=pack_graph_payload_schema,
        pack_manifest_payload_schema=pack_manifest_payload_schema,
        payload_schema_contract_valid=payload_schema_contract_valid,
        native_profile_schema_expected=NATIVE_PROFILE_SCHEMA,
        module_manifest_profile_schema=module_manifest_profile_schema,
        pack_manifest_profile_schema=pack_manifest_profile_schema,
        native_profile_schema_contract_valid=native_profile_schema_contract_valid,
        profile_output_contract_valid=profile_output_contract_valid,
    )


class NativeGraphController:
    """Own one immutable Published Graph instance per Bifrost Scales system."""

    def __init__(
        self,
        cmds_module: Any | None = None,
        evaluation_timeout_seconds: float = DEFAULT_NATIVE_EVALUATION_TIMEOUT_SECONDS,
        evaluation_poll_seconds: float = DEFAULT_NATIVE_EVALUATION_POLL_SECONDS,
    ) -> None:
        if cmds_module is None:
            import maya.cmds as cmds_module  # type: ignore
        self.cmds = cmds_module
        self._last_payload_by_graph: dict[str, str] = {}
        self._evaluation_timeout_seconds = max(
            0.05,
            float(evaluation_timeout_seconds),
        )
        self._evaluation_poll_seconds = max(
            0.001,
            float(evaluation_poll_seconds),
        )
        self._backend_contract_ready = False

    def probe(self) -> NativeBackendStatus:
        return probe_native_backend(cmds_module=self.cmds)

    def _require_backend_ready(self) -> None:
        if self._backend_contract_ready:
            return
        status = self.probe()
        if not status.ready:
            raise RuntimeError(
                "Native Bifrost backend is not ready: {}".format(
                    "; ".join(status.reasons)
                )
            )
        self._backend_contract_ready = True

    def graph_for_system(self, binding: SystemBinding) -> str:
        stored = self._get_string(binding.settings_node, NATIVE_GRAPH_PATH_ATTR)
        if stored and self._is_graph_shape(stored):
            return self._long_name(stored)
        discovered = self._discover_graph(binding.system_id)
        if discovered:
            self._store_graph_reference(binding.settings_node, discovered)
        return discovered

    def create_graph(self, binding: SystemBinding) -> str:
        self._require_backend_ready()
        existing = self.graph_for_system(binding)
        if existing:
            self._validate_graph_contract(existing, require_stamp=True)
            self._validate_graph_target(existing, binding)
            return existing

        before = set(self._list_graph_shapes())
        graph_shape = ""
        try:
            self._validate_target_mesh(binding.target_mesh)
            result = self.cmds.bifrostGraph(importGraphAsShape=GRAPH_DEFINITION)
            graph_shape = self._graph_from_import_result(result)
            if not graph_shape:
                after = set(self._list_graph_shapes())
                created = sorted(after - before)
                if len(created) == 1:
                    graph_shape = created[0]
            if not graph_shape:
                raise RuntimeError(
                    "Bifrost did not return a graph shape for {}".format(
                        GRAPH_DEFINITION
                    )
                )
            graph_shape = self._long_name(graph_shape)
            self._validate_graph_contract(graph_shape, require_stamp=False)
            parent = self._graph_parent(graph_shape)
            self._ensure_bool(parent, NATIVE_GRAPH_OWNER_ATTR, True)
            self._ensure_string(parent, NATIVE_GRAPH_SYSTEM_ATTR, binding.system_id)
            self._ensure_string(parent, NATIVE_GRAPH_OPERATOR_ATTR, OPERATOR_DEFINITION)
            self._ensure_string(parent, NATIVE_GRAPH_CONTRACT_ATTR, GRAPH_CONTRACT)

            # Prefer synchronous graph evaluation when the local Bifrost command
            # exposes ``enableAsync``.  Some Maya 2026 / Bifrost 2.15 builds
            # reject that documented flag at the Python command boundary.
            # Async policy is optional host configuration, not part of the
            # immutable graph contract, so an unsupported flag must not abort
            # graph creation or prevent the Maya DG worldMesh binding.
            async_policy = self._disable_async_if_supported(graph_shape)
            self._ensure_string(
                parent,
                NATIVE_GRAPH_ASYNC_POLICY_ATTR,
                async_policy,
            )

            target_shape = self._long_name(binding.target_mesh)
            scene_path = self._bifrost_scene_path(target_shape)
            source_plug = self._connect_target_world_mesh(
                graph_shape,
                target_shape,
            )

            self._ensure_string(parent, NATIVE_GRAPH_TARGET_PATH_ATTR, scene_path)
            self._ensure_string(
                parent,
                NATIVE_GRAPH_TARGET_UUID_ATTR,
                self._node_uuid(target_shape),
            )
            self._ensure_string(
                parent,
                NATIVE_GRAPH_INPUT_TYPE_ATTR,
                "Object",
            )
            self._ensure_string(
                parent,
                NATIVE_GRAPH_SOURCE_PLUG_ATTR,
                source_plug,
            )
            self._ensure_string(
                parent,
                NATIVE_GRAPH_BINDING_MODE_ATTR,
                "maya-dg-worldMesh",
            )
            evaluation_policy = self._resume_execution_if_supported(graph_shape)
            self._ensure_string(
                parent,
                NATIVE_GRAPH_EVALUATION_POLICY_ATTR,
                evaluation_policy,
            )
            self._store_graph_reference(binding.settings_node, graph_shape)
            self._set_visibility(parent, False)
            self._dirty_graph(graph_shape)
            return graph_shape
        except Exception:
            candidates = [graph_shape] if graph_shape else sorted(
                set(self._list_graph_shapes()) - before
            )
            if len(candidates) == 1:
                self._delete_graph_shape(candidates[0])
            self._clear_graph_reference(binding.settings_node)
            raise

    def invalidate(self, binding: SystemBinding) -> None:
        """Forget the last payload and dirty the existing graph for a fresh pull."""

        graph_shape = self.graph_for_system(binding)
        if not graph_shape:
            raise RuntimeError(
                "Native Graphがありません。Systemを再作成するか、Native Graphを明示的に再構築してください。"
            )
        self._last_payload_by_graph.pop(graph_shape, None)
        self._dirty_graph(graph_shape)

    def delete_graph(self, binding: SystemBinding) -> bool:
        graph_shape = self.graph_for_system(binding)
        self._clear_graph_reference(binding.settings_node)
        if not graph_shape:
            return False
        parent = self._graph_parent(graph_shape)
        self._last_payload_by_graph.pop(graph_shape, None)
        if parent and self.cmds.objExists(parent):
            self.cmds.delete(parent)
        elif self.cmds.objExists(graph_shape):
            self.cmds.delete(graph_shape)
        return True

    def set_active(self, binding: SystemBinding, active: bool, visible: bool = True) -> None:
        graph_shape = self.graph_for_system(binding)
        if graph_shape:
            self._set_visibility(self._graph_parent(graph_shape), bool(active and visible))
        if binding.preview_transform and self.cmds.objExists(binding.preview_transform):
            self._set_visibility(binding.preview_transform, bool((not active) and visible))

    def evaluate(
        self,
        binding: SystemBinding,
        settings: ScaleSettings,
        guides: GuideSet,
        mode: str,
        display_only: bool = False,
        cell_metadata_indices: tuple[int, ...] = (),
        resolve_cell_ids: tuple[str, ...] = (),
    ) -> NativeGraphEvaluation:
        total_started = time.perf_counter()
        self._require_backend_ready()
        graph_shape = self.graph_for_system(binding)
        if not graph_shape:
            raise RuntimeError(
                "Native Graphがありません。新規作成では自動生成されます。既存SystemはNative Graphを明示的に再構築してください。"
            )
        self._validate_graph_contract(graph_shape, require_stamp=True)
        self._validate_graph_target(graph_shape, binding)
        parent = self._graph_parent(graph_shape)

        visibility_started = time.perf_counter()
        self.set_active(binding, active=True, visible=settings.visible)
        viewport_ms = (time.perf_counter() - visibility_started) * 1000.0

        payload_changed = False
        generation_ms = 0.0
        execution_wait_ms = 0.0
        execution_counter_before = -1
        execution_counter_after = -1
        evaluation_policy = self._get_string(
            parent,
            NATIVE_GRAPH_EVALUATION_POLICY_ATTR,
        ) or "direct-pull"
        if not display_only:
            payload = build_native_payload(
                settings,
                guides=guides,
                mode=mode,
                cell_metadata_indices=cell_metadata_indices,
                resolve_cell_ids=resolve_cell_ids,
            )
            if self._last_payload_by_graph.get(graph_shape) != payload:
                generation_started = time.perf_counter()
                previous = self._read_output_snapshot(graph_shape)
                counter_before = self._execution_counter(graph_shape)
                self.cmds.setAttr(
                    graph_shape + ".payload_json",
                    payload,
                    type="string",
                )
                self._dirty_graph(graph_shape)
                resume_policy = self._resume_execution_if_supported(graph_shape)
                wait = self._wait_for_fresh_execution(
                    graph_shape,
                    previous=previous,
                    counter_before=counter_before,
                    policy=resume_policy,
                )
                generation_ms = (time.perf_counter() - generation_started) * 1000.0
                snapshot = wait.snapshot
                execution_wait_ms = wait.waited_ms
                execution_counter_before = wait.counter_before
                execution_counter_after = wait.counter_after
                evaluation_policy = wait.policy
                payload_changed = True
                if snapshot.success:
                    self._last_payload_by_graph[graph_shape] = payload
            else:
                snapshot = self._read_output_snapshot(graph_shape)
        else:
            snapshot = self._read_output_snapshot(graph_shape)

        success = snapshot.success
        status = snapshot.status
        scale_count = snapshot.scale_count
        point_count = snapshot.point_count
        face_count = snapshot.face_count
        if not display_only and not success:
            if status in _TRANSIENT_SOURCE_STATUSES:
                bound_path = self._get_string(parent, NATIVE_GRAPH_TARGET_PATH_ATTR)
                source_plug = self._get_string(parent, NATIVE_GRAPH_SOURCE_PLUG_ATTR)
                binding_mode = self._get_string(parent, NATIVE_GRAPH_BINDING_MODE_ATTR)
                connected = self._connected_source_plugs(graph_shape + ".source_mesh")
                raise RuntimeError(
                    "{}; a fresh Native execution completed, but source_mesh "
                    "still contained no polygon arrays (path={}, source_plug={}, "
                    "binding_mode={}, connected={}, execution_policy={}, "
                    "counter={}->{}).".format(
                        status,
                        bound_path or "missing",
                        source_plug or "missing",
                        binding_mode or "missing",
                        connected or ("none",),
                        evaluation_policy,
                        execution_counter_before,
                        execution_counter_after,
                    )
                )
            raise RuntimeError(status or "Native Bifrost operator evaluation failed")
        total_ms = (time.perf_counter() - total_started) * 1000.0
        return NativeGraphEvaluation(
            graph_shape=graph_shape,
            graph_parent=parent,
            success=success,
            status=status,
            scale_count=scale_count,
            point_count=point_count,
            face_count=face_count,
            payload_changed=payload_changed,
            generation_ms=generation_ms,
            viewport_ms=viewport_ms,
            total_ms=total_ms,
            execution_wait_ms=execution_wait_ms,
            execution_counter_before=execution_counter_before,
            execution_counter_after=execution_counter_after,
            evaluation_policy=evaluation_policy,
            profile=_parse_native_profile(snapshot.profile_json),
        )

    def _validate_graph_contract(
        self,
        graph_shape: str,
        require_stamp: bool = True,
    ) -> None:
        missing = [
            name
            for name in _REQUIRED_GRAPH_ATTRIBUTES
            if not self.cmds.attributeQuery(name, node=graph_shape, exists=True)
        ]
        if missing:
            raise RuntimeError(
                "Native Published Graph contract is incomplete on {}: {}".format(
                    graph_shape, ", ".join(missing)
                )
            )
        if not require_stamp:
            return
        parent = self._graph_parent(graph_shape)
        operator_stamp = (
            self._get_string(parent, NATIVE_GRAPH_OPERATOR_ATTR) if parent else ""
        )
        contract_stamp = (
            self._get_string(parent, NATIVE_GRAPH_CONTRACT_ATTR) if parent else ""
        )
        if (
            operator_stamp != OPERATOR_DEFINITION
            or contract_stamp != GRAPH_CONTRACT
        ):
            raise RuntimeError(
                "This Native Graph uses an obsolete operator namespace or graph "
                "contract. Delete the Native Graph and create a new one with Bifrost Scales 0.10.9."
            )

    def _discover_graph(self, system_id: str) -> str:
        if not system_id:
            return ""
        for transform in self.cmds.ls(type="transform", long=True) or []:
            try:
                if not self.cmds.attributeQuery(
                    NATIVE_GRAPH_OWNER_ATTR, node=transform, exists=True
                ):
                    continue
                if not bool(self.cmds.getAttr(transform + "." + NATIVE_GRAPH_OWNER_ATTR)):
                    continue
                if self._get_string(transform, NATIVE_GRAPH_SYSTEM_ATTR) != system_id:
                    continue
                shapes = self.cmds.listRelatives(
                    transform,
                    shapes=True,
                    noIntermediate=True,
                    fullPath=True,
                    type="bifrostGraphShape",
                ) or []
                if shapes:
                    return self._long_name(str(shapes[0]))
            except Exception:
                continue
        return ""

    def _store_graph_reference(self, settings_node: str, graph_shape: str) -> None:
        self._ensure_string(settings_node, NATIVE_GRAPH_PATH_ATTR, self._long_name(graph_shape))
        uuid_values = self.cmds.ls(graph_shape, uuid=True) or []
        self._ensure_string(
            settings_node,
            NATIVE_GRAPH_UUID_ATTR,
            str(uuid_values[0]) if uuid_values else "",
        )

    def _clear_graph_reference(self, settings_node: str) -> None:
        self._ensure_string(settings_node, NATIVE_GRAPH_PATH_ATTR, "")
        self._ensure_string(settings_node, NATIVE_GRAPH_UUID_ATTR, "")

    def _graph_from_import_result(self, result: Any) -> str:
        candidates: list[str] = []
        if isinstance(result, str):
            candidates.append(result)
        elif isinstance(result, (list, tuple)):
            candidates.extend(str(item) for item in result)
        for candidate in candidates:
            if not self.cmds.objExists(candidate):
                continue
            if self._is_graph_shape(candidate):
                return candidate
            try:
                shapes = self.cmds.listRelatives(
                    candidate,
                    shapes=True,
                    noIntermediate=True,
                    fullPath=True,
                    type="bifrostGraphShape",
                ) or []
                if shapes:
                    return str(shapes[0])
            except Exception:
                continue
        return ""

    def _list_graph_shapes(self) -> list[str]:
        return [self._long_name(str(node)) for node in (self.cmds.ls(type="bifrostGraphShape", long=True) or [])]

    def _delete_graph_shape(self, graph_shape: str) -> None:
        if not graph_shape or not self.cmds.objExists(graph_shape):
            return
        parent = self._graph_parent(graph_shape)
        if parent and self.cmds.objExists(parent):
            self.cmds.delete(parent)
        else:
            self.cmds.delete(graph_shape)

    def _is_graph_shape(self, node: str) -> bool:
        try:
            return bool(self.cmds.objExists(node) and self.cmds.nodeType(node) == "bifrostGraphShape")
        except Exception:
            return False

    def _graph_parent(self, graph_shape: str) -> str:
        parents = self.cmds.listRelatives(graph_shape, parent=True, fullPath=True) or []
        return str(parents[0]) if parents else ""

    def _long_name(self, node: str) -> str:
        values = self.cmds.ls(node, long=True) or []
        return str(values[0]) if values else str(node)

    @staticmethod
    def _bifrost_scene_path(target_shape: str) -> str:
        path = str(target_shape).replace("|", "/")
        if not path.startswith("/"):
            path = "/" + path
        while "//" in path:
            path = path.replace("//", "/")
        return path

    def _validate_target_mesh(self, target_shape: str) -> None:
        target = self._long_name(target_shape)
        if not target or not self.cmds.objExists(target):
            raise RuntimeError("Native target mesh does not exist: {}".format(target_shape))
        if self.cmds.nodeType(target) != "mesh":
            raise RuntimeError("Native target must be a Maya mesh shape: {}".format(target))
        try:
            if bool(self.cmds.getAttr(target + ".intermediateObject")):
                raise RuntimeError("Native target is an intermediate mesh shape: {}".format(target))
        except RuntimeError:
            raise
        except Exception:
            pass

        # polyEvaluate forces Maya construction history to produce the mesh
        # before Bifrost resolves the scene path.  The seam is optional in unit
        # tests and on stripped-down Maya command shims.
        if hasattr(self.cmds, "polyEvaluate"):
            try:
                vertices = int(self.cmds.polyEvaluate(target, vertex=True) or 0)
                faces = int(self.cmds.polyEvaluate(target, face=True) or 0)
            except Exception as exc:
                raise RuntimeError(
                    "Could not evaluate Native target mesh {} ({})".format(target, exc)
                ) from exc
            if vertices <= 0 or faces <= 0:
                raise RuntimeError(
                    "Native target mesh has no polygon data: {} (vertices={}, faces={})".format(
                        target,
                        vertices,
                        faces,
                    )
                )

    def _disable_async_if_supported(self, graph_shape: str) -> str:
        """Disable async evaluation when supported by the installed command.

        Autodesk documents ``enableAsync`` for ``bifrostGraph``, but the Maya
        Python wrapper shipped with some Bifrost 2.15 installations rejects the
        keyword with ``TypeError: Invalid flag 'enableAsync'``.  The setting is
        an execution preference only.  Treat that specific incompatibility as
        optional and continue with the immutable graph and verified scene input.

        Returns:
            ``"disabled"`` when the command accepted the flag, otherwise
            ``"unsupported"`` when the local command does not expose it.

        Unexpected runtime failures are re-raised so graph setup does not hide
        genuine Bifrost or scene errors.
        """

        try:
            self.cmds.bifrostGraph(graph_shape, enableAsync=False)
            return "disabled"
        except TypeError:
            # Maya's generated command wrapper uses TypeError for unknown flags.
            return "unsupported"
        except RuntimeError as exc:
            message = str(exc).lower()
            if (
                "enableasync" in message
                or "invalid flag" in message
                or "unknown flag" in message
                or "unrecognized flag" in message
            ):
                return "unsupported"
            raise

    def _resume_execution_if_supported(self, graph_shape: str) -> str:
        """Ensure a graph is not left paused by ``runOnDemand``.

        This is deliberately best-effort.  Bifrost 2.15 installations differ
        in which ``bifrostGraph`` flags are exposed through the generated Maya
        Python command wrapper.  A missing execution-policy flag must not be
        confused with a graph or operator failure.
        """

        try:
            self.cmds.bifrostGraph(graph_shape, runOnDemand=False)
            return "run-on-demand-resumed"
        except TypeError:
            return "unsupported"
        except RuntimeError as exc:
            message = str(exc).lower()
            if (
                "runondemand" in message
                or "invalid flag" in message
                or "unknown flag" in message
                or "unrecognized flag" in message
            ):
                return "unsupported"
            raise

    def _execution_counter(self, graph_shape: str) -> int | None:
        """Return the normal-context execution counter when supported."""

        try:
            raw = self.cmds.bifrostGraph(
                graph_shape,
                executionCounter="normal",
            )
        except Exception:
            return None
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        try:
            return int(raw)
        except (TypeError, ValueError):
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return None

    def _read_output_snapshot(self, graph_shape: str) -> _NativeOutputSnapshot:
        profile_json = ""
        try:
            if self.cmds.attributeQuery(
                "profile_json", node=graph_shape, exists=True
            ):
                profile_json = str(
                    self._safe_get(graph_shape + ".profile_json", "") or ""
                )
        except Exception:
            # Existing Graph v4 instances remain valid when their host binding contract is intact.
            profile_json = ""
        return _NativeOutputSnapshot(
            success=bool(self._safe_get(graph_shape + ".success", False)),
            status=str(self._safe_get(graph_shape + ".status", "") or ""),
            scale_count=int(
                self._safe_get(graph_shape + ".scale_count", 0) or 0
            ),
            point_count=int(
                self._safe_get(graph_shape + ".point_count", 0) or 0
            ),
            face_count=int(self._safe_get(graph_shape + ".face_count", 0) or 0),
            profile_json=profile_json,
        )

    def _pump_host_events(self) -> None:
        """Allow an asynchronous Bifrost result to publish back to Maya."""

        try:
            import maya.utils as maya_utils  # type: ignore

            process_idle = getattr(maya_utils, "processIdleEvents", None)
            if callable(process_idle):
                process_idle()
        except Exception:
            pass
        refresh = getattr(self.cmds, "refresh", None)
        if callable(refresh):
            try:
                refresh(force=True)
            except Exception:
                pass
        time.sleep(self._evaluation_poll_seconds)

    def _wait_for_fresh_execution(
        self,
        graph_shape: str,
        previous: _NativeOutputSnapshot,
        counter_before: int | None,
        policy: str,
    ) -> _NativeExecutionWait:
        """Wait for the evaluation requested by the latest payload mutation.

        When async mode cannot be disabled, immediately reading a graph output
        returns whatever value was published previously.  On a newly imported
        graph that previous value can be the first evaluation performed before
        the Maya DG worldMesh connection was established, which reports an empty
        source mesh.

        This method does not submit repeated evaluations.  It performs one
        output pull and then waits for either the documented execution counter
        to advance or, on old hosts without that counter, a settled output
        fingerprint change.
        """

        started = time.monotonic()
        deadline = started + self._evaluation_timeout_seconds
        fallback_accept_at = started + max(
            0.05,
            self._evaluation_poll_seconds * 3.0,
        )
        counter_floor = counter_before
        latest_counter = counter_before
        transient_candidate: _NativeOutputSnapshot | None = None
        transient_counter = counter_before

        # One pull requests evaluation.  In async mode the value returned here
        # can still be stale, so it is intentionally ignored.
        try:
            self.cmds.getAttr(graph_shape + ".success")
        except Exception:
            pass

        while True:
            # Query the counter before reading outputs, then confirm it again.
            # This avoids returning a snapshot read just before the background
            # execution published and incremented its counter.
            counter_after = self._execution_counter(graph_shape)
            snapshot = self._read_output_snapshot(graph_shape)
            counter_confirmed = self._execution_counter(graph_shape)
            if counter_confirmed is not None:
                counter_after = counter_confirmed
            if counter_after is not None:
                latest_counter = counter_after
            now = time.monotonic()

            counter_advanced = (
                counter_floor is not None
                and counter_after is not None
                and counter_after > counter_floor
            )
            if counter_advanced:
                # Re-read after observing the increment so all returned output
                # fields belong to the completed execution, not the preceding
                # published snapshot.
                snapshot = self._read_output_snapshot(graph_shape)
                if snapshot.success or snapshot.status not in _TRANSIENT_SOURCE_STATUSES:
                    return _NativeExecutionWait(
                        snapshot=snapshot,
                        waited_ms=(now - started) * 1000.0,
                        counter_before=(
                            counter_before if counter_before is not None else -1
                        ),
                        counter_after=counter_after,
                        policy="{}+execution-counter".format(policy),
                    )

                # An import-time or pre-binding evaluation can finish after the
                # payload update and advance the same counter.  Do not accept
                # its empty-source status yet; remember it and wait for the next
                # execution.  If no later execution arrives, the candidate is
                # returned at the deadline as a genuine persistent input error.
                transient_candidate = snapshot
                transient_counter = counter_after
                counter_floor = counter_after

            # When the command exposes an execution counter, it is the
            # authoritative freshness signal.  A newly imported async graph can
            # change its published outputs from "not evaluated" to the stale
            # pre-binding error without executing the payload mutation we just
            # submitted.  Accepting that fingerprint change would reproduce the
            # exact false empty-mesh failure seen in Maya 2026 / Bifrost 2.15.
            counter_supported = (
                counter_before is not None or counter_after is not None
            )

            # Older command wrappers may expose neither enableAsync nor
            # executionCounter.  In that case, give Maya several idle cycles
            # before using an output change as the best available freshness
            # signal.  Never use output-change fallback while a counter exists.
            if (
                not counter_supported
                and now >= fallback_accept_at
                and snapshot.fingerprint() != previous.fingerprint()
            ):
                if snapshot.status in _TRANSIENT_SOURCE_STATUSES and not snapshot.success:
                    transient_candidate = snapshot
                    transient_counter = None
                else:
                    return _NativeExecutionWait(
                        snapshot=snapshot,
                        waited_ms=(now - started) * 1000.0,
                        counter_before=-1,
                        counter_after=-1,
                        policy="{}+output-change-after-idle".format(policy),
                    )

            if (
                not counter_supported
                and snapshot.success
                and now >= fallback_accept_at
            ):
                return _NativeExecutionWait(
                    snapshot=snapshot,
                    waited_ms=(now - started) * 1000.0,
                    counter_before=-1,
                    counter_after=-1,
                    policy="{}+idle-settle".format(policy),
                )

            if now >= deadline:
                if transient_candidate is not None:
                    return _NativeExecutionWait(
                        snapshot=transient_candidate,
                        waited_ms=(now - started) * 1000.0,
                        counter_before=(
                            counter_before if counter_before is not None else -1
                        ),
                        counter_after=(
                            transient_counter if transient_counter is not None else -1
                        ),
                        policy="{}+persistent-source-failure".format(policy),
                    )
                async_policy = self._get_string(
                    self._graph_parent(graph_shape),
                    NATIVE_GRAPH_ASYNC_POLICY_ATTR,
                )
                raise RuntimeError(
                    "Native Bifrost graph did not publish a fresh execution "
                    "within {:.2f}s (execution_counter_before={}, "
                    "execution_counter_after={}, async_policy={}, "
                    "last_status={!r}). The graph was requested once and was "
                    "not retried.".format(
                        self._evaluation_timeout_seconds,
                        counter_before if counter_before is not None else "unsupported",
                        latest_counter if latest_counter is not None else "unsupported",
                        async_policy or "unknown",
                        snapshot.status,
                    )
                )

            self._pump_host_events()


    def _connect_target_world_mesh(
        self,
        graph_shape: str,
        target_shape: str,
    ) -> str:
        """Connect Maya's evaluated world-space mesh to the graph input.

        Maya serializes working Bifrost mesh inputs as a DG connection from
        ``meshShape.worldMesh`` to the graph's top-level mesh input attribute.
        ``inputByPathSuggestedTypes`` only proves that a scene path *could*
        resolve to ``Object``; it does not prove that the imported graph shape
        actually received polygon data.  Use the concrete Maya DG connection
        as the authoritative host boundary instead.
        """

        destination = graph_shape + ".source_mesh"
        if not self.cmds.attributeQuery(
            "source_mesh",
            node=graph_shape,
            exists=True,
        ):
            raise RuntimeError(
                "Native Published Graph does not expose the source_mesh input attribute"
            )

        source_candidates = (
            target_shape + ".worldMesh[0]",
            target_shape + ".worldMesh",
        )
        failures: list[str] = []
        for source in source_candidates:
            try:
                self.cmds.connectAttr(source, destination, force=True)
            except Exception as exc:
                failures.append("{}: {}".format(source, exc))
                continue
            connected = self._connected_source_plugs(destination)
            if any(self._plugs_equivalent(source, item) for item in connected):
                return self._normalize_plug(source)
            failures.append(
                "{}: Maya accepted connectAttr but listConnections returned {}".format(
                    source,
                    connected or ("none",),
                )
            )

        raise RuntimeError(
            "Could not connect the Maya target mesh to Native source_mesh. "
            "Tried {} -> {} ({})".format(
                source_candidates,
                destination,
                "; ".join(failures) or "no diagnostic",
            )
        )

    def _connected_source_plugs(self, destination_plug: str) -> tuple[str, ...]:
        try:
            values = self.cmds.listConnections(
                destination_plug,
                source=True,
                destination=False,
                plugs=True,
            ) or []
        except Exception:
            return ()
        return tuple(str(value) for value in values if str(value))

    def _normalize_plug(self, plug: str) -> str:
        value = str(plug or "")
        node, separator, attribute = value.rpartition(".")
        if not separator or not node:
            return value
        try:
            long_names = self.cmds.ls(node, long=True) or []
        except Exception:
            long_names = []
        normalized_node = str(long_names[0]) if long_names else node
        return normalized_node + "." + attribute

    def _plugs_equivalent(self, first: str, second: str) -> bool:
        first_normalized = self._normalize_plug(first)
        second_normalized = self._normalize_plug(second)

        def parts(value: str) -> tuple[str, str]:
            node, separator, attribute = value.rpartition(".")
            if not separator:
                return value, ""
            return node, re.sub(r"\[\d+\]$", "", attribute)

        first_node, first_attribute = parts(first_normalized)
        second_node, second_attribute = parts(second_normalized)
        if first_attribute != second_attribute:
            return False
        if first_node == second_node:
            return True

        try:
            first_uuids = set(self.cmds.ls(first_node, uuid=True) or [])
            second_uuids = set(self.cmds.ls(second_node, uuid=True) or [])
        except Exception:
            return False
        return bool(first_uuids and second_uuids and first_uuids.intersection(second_uuids))

    def _node_uuid(self, node: str) -> str:
        try:
            values = self.cmds.ls(node, uuid=True) or []
            return str(values[0]) if values else ""
        except Exception:
            return ""

    def _validate_graph_target(
        self,
        graph_shape: str,
        binding: SystemBinding,
    ) -> None:
        parent = self._graph_parent(graph_shape)
        if not parent:
            raise RuntimeError("Native Graph has no parent transform")
        stored_path = self._get_string(parent, NATIVE_GRAPH_TARGET_PATH_ATTR)
        stored_uuid = self._get_string(parent, NATIVE_GRAPH_TARGET_UUID_ATTR)
        stored_type = self._get_string(parent, NATIVE_GRAPH_INPUT_TYPE_ATTR)
        stored_source = self._get_string(parent, NATIVE_GRAPH_SOURCE_PLUG_ATTR)
        binding_mode = self._get_string(parent, NATIVE_GRAPH_BINDING_MODE_ATTR)
        current_target = self._long_name(binding.target_mesh)
        current_uuid = self._node_uuid(current_target)
        if (
            not stored_path
            or "Object" not in stored_type
            or not stored_source
            or binding_mode != "maya-dg-worldMesh"
        ):
            raise RuntimeError(
                "Native Graph has no verified Maya worldMesh DG binding. "
                "Delete the Native Graph and create it again with Bifrost Scales 0.10.9."
            )
        if stored_uuid and current_uuid and stored_uuid != current_uuid:
            raise RuntimeError(
                "Native Graph is bound to a different target mesh. Delete and recreate it."
            )
        destination = graph_shape + ".source_mesh"
        connected = self._connected_source_plugs(destination)
        if not any(
            self._plugs_equivalent(stored_source, item)
            for item in connected
        ):
            raise RuntimeError(
                "Native Graph source_mesh is not connected to the stored Maya worldMesh "
                "plug (expected={}, actual={}). Delete and recreate it.".format(
                    stored_source,
                    connected or ("none",),
                )
            )
        self._validate_target_mesh(current_target)

    def _dirty_graph(self, graph_shape: str) -> None:
        if not hasattr(self.cmds, "dgdirty"):
            return
        try:
            self.cmds.dgdirty(graph_shape)
        except Exception:
            pass

    def _set_visibility(self, transform: str, visible: bool) -> None:
        if transform and self.cmds.objExists(transform):
            try:
                current = bool(self.cmds.getAttr(transform + ".visibility"))
            except Exception:
                current = not bool(visible)
            if current != bool(visible):
                self.cmds.setAttr(transform + ".visibility", bool(visible))

    def _safe_get(self, plug: str, fallback: Any) -> Any:
        try:
            return self.cmds.getAttr(plug)
        except Exception:
            return fallback

    def _get_string(self, node: str, name: str) -> str:
        try:
            if self.cmds.attributeQuery(name, node=node, exists=True):
                return str(self.cmds.getAttr(node + "." + name) or "")
        except Exception:
            pass
        return ""

    def _ensure_string(self, node: str, name: str, value: str) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, dataType="string")
        self.cmds.setAttr(node + "." + name, str(value), type="string")

    def _ensure_bool(self, node: str, name: str, value: bool) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, attributeType="bool")
        self.cmds.setAttr(node + "." + name, bool(value))
