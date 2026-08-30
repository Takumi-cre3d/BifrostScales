import json
from dataclasses import replace
from pathlib import Path

import pytest

import bifrost_scales.native_backend as native_backend
from bifrost_scales.guides import GuideSet
from bifrost_scales.native_backend import (
    NativeBackendStatus,
    NativeGraphController,
    probe_native_backend,
)
from bifrost_scales.scene import SystemBinding
from bifrost_scales.settings import ScaleSettings


class FakeNativeCmds:
    def __init__(self):
        self.nodes = {
            "settings1": {"type": "network", "attrs": {}},
            "targetShape": {"type": "mesh", "attrs": {"intermediateObject": False, "worldMesh": None}, "vertices": 4, "faces": 1},
            "preview1": {"type": "transform", "attrs": {"visibility": True}, "children": []},
        }
        self.calls = []
        self.connect_calls = []
        self.connections = {}
        self.set_attr_calls = []
        self._counter = 0
        self.execution_counter = 0

    def objExists(self, node):
        return node in self.nodes

    def nodeType(self, node):
        return self.nodes[node]["type"]

    def attributeQuery(self, name, node, exists=False):
        assert exists
        return name in self.nodes[node].setdefault("attrs", {})

    def addAttr(self, node, longName, attributeType=None, dataType=None):
        del attributeType, dataType
        self.nodes[node].setdefault("attrs", {})[longName] = None

    def setAttr(self, plug, value, **kwargs):
        self.set_attr_calls.append((plug, value, dict(kwargs)))
        del kwargs
        node, attr = plug.rsplit(".", 1)
        self.nodes[node]["attrs"][attr] = value
        if attr == "payload_json":
            self.nodes[node]["attrs"].update(
                success=True,
                status="ok",
                scale_count=32,
                point_count=256,
                face_count=224,
                profile_json=json.dumps(
                    {
                        "schema": "bifrost-scales/native-profile/9",
                        "distribution_ms": 3.0,
                        "orientation_ms": 2.0,
                        "orientation_prepare_ms": 0.4,
                        "direction_neighbors_ms": 0.3,
                        "direction_neighbors_cache_hit": True,
                        "direction_relax_ms": 0.8,
                        "direction_relax_pack_ms": 0.1,
                        "direction_relax_gpu_call_ms": 0.6,
                        "direction_relax_unpack_ms": 0.1,
                        "orientation_finalize_ms": 0.5,
                        "cells_ms": 4.0,
                        "shape_ms": 1.0,
                        "core_total_ms": 10.0,
                        "operator_total_ms": 12.0,
                    }
                ),
            )
            self.execution_counter += 1

    def getAttr(self, plug):
        node, attr = plug.rsplit(".", 1)
        return self.nodes[node]["attrs"].get(attr)

    def ls(self, node=None, type=None, long=False, uuid=False, **kwargs):
        del long, kwargs
        if uuid:
            return ["uuid-{}".format(node)] if node in self.nodes else []
        if node is not None and type is None:
            return [node] if node in self.nodes else []
        return [name for name, data in self.nodes.items() if type is None or data["type"] == type]

    def listRelatives(self, node, parent=False, shapes=False, type=None, **kwargs):
        del kwargs
        if parent:
            value = self.nodes[node].get("parent")
            return [value] if value else []
        values = list(self.nodes[node].get("children", []))
        if shapes:
            values = [item for item in values if self.nodes[item]["type"] != "transform"]
        if type is not None:
            values = [item for item in values if self.nodes[item]["type"] == type]
        return values

    def bifrostGraph(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if "importGraphAsShape" in kwargs:
            self._counter += 1
            transform = "nativeGraph{}".format(self._counter)
            shape = transform + "Shape"
            self.nodes[transform] = {
                "type": "transform",
                "attrs": {"visibility": True},
                "children": [shape],
            }
            self.nodes[shape] = {
                "type": "bifrostGraphShape",
                "attrs": {
                    "source_mesh": None,
                    "payload_json": "",
                    "success": False,
                    "status": "not evaluated",
                    "scale_count": 0,
                    "point_count": 0,
                    "face_count": 0,
                    "profile_json": "",
                },
                "parent": transform,
            }
            return transform
        if "inputByPathSuggestedTypes" in kwargs:
            return ["Object"]
        if "executionCounter" in kwargs:
            return self.execution_counter
        return None

    def connectAttr(self, source, destination, force=False):
        self.connect_calls.append((source, destination, bool(force)))
        if not force and destination in self.connections:
            raise RuntimeError("already connected")
        self.connections[destination] = source

    def disconnectAttr(self, source, destination):
        if self.connections.get(destination) == source:
            self.connections.pop(destination, None)

    def listConnections(self, plug, source=True, destination=False, plugs=False):
        if source and not destination:
            value = self.connections.get(plug)
            if value is None:
                return []
            return [value if plugs else value.rsplit(".", 1)[0]]
        return []

    def polyEvaluate(self, node, vertex=False, face=False):
        if vertex:
            return self.nodes[node].get("vertices", 0)
        if face:
            return self.nodes[node].get("faces", 0)
        return 0

    def dgdirty(self, node):
        self.nodes[node]["dirty"] = True

    def refresh(self, force=False):
        del force

    def delete(self, node):
        children = list(self.nodes.get(node, {}).get("children", []))
        for child in children:
            self.nodes.pop(child, None)
        self.nodes.pop(node, None)


class FakeNoEnableAsyncCmds(FakeNativeCmds):
    """Mimic Maya 2026 / Bifrost 2.15 rejecting enableAsync."""

    def bifrostGraph(self, *args, **kwargs):
        if "enableAsync" in kwargs:
            self.calls.append((args, kwargs))
            raise TypeError("Invalid flag 'enableAsync'")
        return super().bifrostGraph(*args, **kwargs)


class FakeUnexpectedAsyncFailureCmds(FakeNativeCmds):
    def bifrostGraph(self, *args, **kwargs):
        if "enableAsync" in kwargs:
            self.calls.append((args, kwargs))
            raise RuntimeError("native graph execution policy is corrupt")
        return super().bifrostGraph(*args, **kwargs)


class FakeAsyncStaleResultCmds(FakeNoEnableAsyncCmds):
    """Publish the pre-binding error until Maya gets an idle/refresh cycle."""

    def __init__(self):
        super().__init__()
        self.pending_graph = ""

    def setAttr(self, plug, value, **kwargs):
        self.set_attr_calls.append((plug, value, dict(kwargs)))
        node, attr = plug.rsplit(".", 1)
        if attr != "payload_json":
            # Avoid recording the same call twice in the base implementation.
            del self.set_attr_calls[-1]
            return super().setAttr(plug, value, **kwargs)
        del kwargs
        self.nodes[node]["attrs"][attr] = value
        self.nodes[node]["attrs"].update(
            success=False,
            status="source mesh has no positions",
            scale_count=0,
            point_count=0,
            face_count=0,
        )
        self.pending_graph = node

    def refresh(self, force=False):
        del force
        if not self.pending_graph:
            return
        node = self.pending_graph
        self.nodes[node]["attrs"].update(
            success=True,
            status="ok",
            scale_count=32,
            point_count=256,
            face_count=224,
        )
        self.execution_counter += 1
        self.pending_graph = ""


class FakeTwoStageAsyncCmds(FakeAsyncStaleResultCmds):
    """First completes the old pre-binding run, then the payload run."""

    def __init__(self):
        super().__init__()
        self.refresh_stage = 0

    def refresh(self, force=False):
        del force
        if not self.pending_graph:
            return
        node = self.pending_graph
        self.refresh_stage += 1
        self.execution_counter += 1
        if self.refresh_stage == 1:
            # The old import-time execution completes first and republishes the
            # same empty-source result.  The latest payload is still pending.
            self.nodes[node]["attrs"].update(
                success=False,
                status="source mesh has no positions",
                scale_count=0,
                point_count=0,
                face_count=0,
            )
            return
        self.nodes[node]["attrs"].update(
            success=True,
            status="ok",
            scale_count=32,
            point_count=256,
            face_count=224,
        )
        self.pending_graph = ""


class FakeNeverPublishesCmds(FakeNoEnableAsyncCmds):
    def setAttr(self, plug, value, **kwargs):
        self.set_attr_calls.append((plug, value, dict(kwargs)))
        node, attr = plug.rsplit(".", 1)
        if attr != "payload_json":
            del self.set_attr_calls[-1]
            return super().setAttr(plug, value, **kwargs)
        del kwargs
        self.nodes[node]["attrs"][attr] = value
        self.nodes[node]["attrs"].update(
            success=False,
            status="source mesh has no positions",
            scale_count=0,
            point_count=0,
            face_count=0,
        )


class FakeCatalogCmds:
    def __init__(self, include_operator=True):
        self.include_operator = include_operator

    def bifrostGraph(self, *args, **kwargs):
        del args, kwargs
        return None

    def vnn(self, **kwargs):
        if kwargs.get("runTimes"):
            return ["BifrostGraph"]
        if kwargs.get("libraries") == "BifrostGraph":
            return ["BifrostScales"]
        if kwargs.get("nodes") in (
            ["BifrostGraph", "BifrostScales"],
            ("BifrostGraph", "BifrostScales"),
        ):
            if self.include_operator:
                return ["BifrostScales::generate_scale_mesh_payload_arrays"]
            return ["BifrostScales::some_other_node"]
        return []


class FakeDoubledNamespaceCmds(FakeCatalogCmds):
    def vnn(self, **kwargs):
        if kwargs.get("runTimes"):
            return ["BifrostGraph"]
        if kwargs.get("libraries") == "BifrostGraph":
            return ["BifrostScales::BifrostScales"]
        if kwargs.get("nodes") in (
            ["BifrostGraph", "BifrostScales::BifrostScales"],
            ("BifrostGraph", "BifrostScales::BifrostScales"),
        ):
            return ["generate_scale_mesh_payload_arrays"]
        return []


class FakeMixedNamespaceCmds(FakeCatalogCmds):
    def vnn(self, **kwargs):
        if kwargs.get("runTimes"):
            return ["BifrostGraph"]
        if kwargs.get("libraries") == "BifrostGraph":
            return ["BifrostScales::BifrostScales", "BifrostScales"]
        nodes = kwargs.get("nodes")
        if nodes in (
            ["BifrostGraph", "BifrostScales::BifrostScales"],
            ("BifrostGraph", "BifrostScales::BifrostScales"),
        ):
            return ["generate_scale_mesh_payload_arrays"]
        if nodes in (
            ["BifrostGraph", "BifrostScales"],
            ("BifrostGraph", "BifrostScales"),
        ):
            return ["generate_scale_mesh_payload_arrays"]
        return []


def _ready_status():
    return NativeBackendStatus(
        module_root="/module",
        graph_asset="/module/graph.json",
        pack_config="/module/pack.json",
        operator_binary="/module/BifrostScalesOps.dll",
        nodedef_json="/module/nodedef.json",
        graph_asset_available=True,
        pack_config_available=True,
        pack_config_registered=True,
        pack_config_active=True,
        definition_library_registered=True,
        operator_binary_available=True,
        nodedef_available=True,
        bifrost_command_available=True,
        catalog_query_available=True,
        operator_definition_available=True,
        catalog_match="BifrostScales::generate_scale_mesh_payload_arrays",
        restart_required=False,
        ready=True,
        reasons=(),
        pack_version="0.10.7",
        minimum_pack_version="0.10.7",
        payload_schema_expected="bifrost-scales/native-payload/10",
        module_graph_payload_schema="bifrost-scales/native-payload/10",
        module_manifest_payload_schema="bifrost-scales/native-payload/10",
        pack_graph_payload_schema="bifrost-scales/native-payload/10",
        pack_manifest_payload_schema="bifrost-scales/native-payload/10",
        payload_schema_contract_valid=True,
        native_behavior_contract_valid=True,
        native_profile_schema_expected="bifrost-scales/native-profile/9",
        module_manifest_profile_schema="bifrost-scales/native-profile/9",
        pack_manifest_profile_schema="bifrost-scales/native-profile/9",
        native_profile_schema_contract_valid=True,
        profile_output_contract_valid=True,
    )


def test_probe_is_read_only_and_reports_unbuilt_pack_in_source_tree():
    status = probe_native_backend(cmds_module=object())
    assert status.graph_asset_available is True
    assert status.pack_config_available is False
    assert status.ready is False
    assert any("PackConfig" in reason for reason in status.reasons)



def _write_nested_native_pack(module_root: Path, version: str = "0.10.7") -> Path:
    graph_source = (
        module_root
        / "bifrost"
        / "compounds"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    graph_source.parent.mkdir(parents=True, exist_ok=True)
    graph_source.write_text(
        (Path(__file__).resolve().parents[1]
         / "BifrostScales"
         / "bifrost"
         / "compounds"
         / "BifrostScales_native_scales_v4_graph.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    module_manifest = graph_source.parent / "manifest.bifrost-scales.json"
    module_manifest.write_text(
        json.dumps(
            {
                "native_payload_schema": "bifrost-scales/native-payload/10",
                "native_behavior_contract": "bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1",
                "native_profile_schema": "bifrost-scales/native-profile/9",
            }
        ),
        encoding="utf-8",
    )

    pack_root = (
        module_root
        / "bifrost"
        / "pack"
        / "BifrostScalesCore-{}".format(version)
    )
    pack_config = pack_root / "BifrostScalesPackConfig.json"
    pack_config.parent.mkdir(parents=True, exist_ok=True)
    pack_config.write_text(
        '{"AminoConfigurations":[{"jsonLibs":['
        '{"path":"./json/BifrostScales/operators","files":["bifrost_scales_nodedef.json"]},'
        '{"path":"./json/BifrostScales/graphs","files":["BifrostScales_native_scales_v4_graph.json"]}'
        ']}]}',
        encoding="utf-8",
    )
    operator = pack_root / "lib" / "BifrostScalesOps.dll"
    operator.parent.mkdir(parents=True, exist_ok=True)
    operator.write_bytes(b"dll")
    nodedef = (
        pack_root
        / "json"
        / "BifrostScales"
        / "operators"
        / "bifrost_scales_nodedef.json"
    )
    nodedef.parent.mkdir(parents=True, exist_ok=True)
    nodedef.write_text(
        json.dumps(
            {
                "operators": [
                    {
                        "name": "BifrostScales::generate_scale_mesh_payload_arrays",
                        "ports": [
                            {"portName": "source_face_offset", "portType": "array<uint>"},
                            {"portName": "source_face_vertex", "portType": "array<uint>"},
                            {"portName": "face_offset", "portType": "array<uint>"},
                            {"portName": "face_vertex", "portType": "array<uint>"},
                            {"portName": "profile_json", "portType": "string"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    installed_graph = (
        pack_root
        / "json"
        / "BifrostScales"
        / "graphs"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    installed_graph.parent.mkdir(parents=True, exist_ok=True)
    installed_graph.write_text(graph_source.read_text(encoding="utf-8"), encoding="utf-8")
    metadata = pack_root / "metadata" / "manifest.bifrost-scales.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(
        json.dumps(
            {
                "native_payload_schema": "bifrost-scales/native-payload/10",
                "native_behavior_contract": "bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1",
                "native_profile_schema": "bifrost-scales/native-profile/9",
            }
        ),
        encoding="utf-8",
    )
    return pack_config


def test_probe_resolves_versioned_bifrost_215_install_prefix(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert status.ready is True
    assert status.pack_config_registered is True
    assert status.pack_config_active is True
    assert status.operator_definition_available is True
    assert status.definition_library_registered is True
    assert status.graph_library_registered is True
    assert status.pack_resources_isolated is True
    assert status.mesh_topology_contract_valid is True
    assert status.pack_version == "0.10.7"
    assert status.minimum_pack_version == "0.10.7"
    assert status.native_behavior_contract_valid is True
    assert status.native_behavior_contract_expected == "bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1"
    assert status.module_native_behavior_contract == status.native_behavior_contract_expected
    assert status.pack_native_behavior_contract == status.native_behavior_contract_expected
    assert status.payload_schema_contract_valid is True
    assert status.payload_schema_expected == "bifrost-scales/native-payload/10"
    assert status.pack_graph_payload_schema == "bifrost-scales/native-payload/10"
    assert status.pack_manifest_payload_schema == "bifrost-scales/native-payload/10"
    assert dict(status.nodedef_port_types)["face_offset"] == "array<uint>"
    assert status.catalog_runtime == "BifrostGraph"
    assert Path(status.pack_config) == pack_config
    assert Path(status.operator_binary).name == "BifrostScalesOps.dll"
    assert Path(status.nodedef_json).name == "bifrost_scales_nodedef.json"



def test_probe_rejects_pre_090_native_behavior_contract(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root, version="0.8.3")
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert status.ready is False
    assert status.pack_version == "0.8.3"
    assert status.minimum_pack_version == "0.10.7"
    assert status.native_behavior_contract_valid is False
    assert status.rebuild_required is True
    assert any("older than the required 0.10.7" in reason for reason in status.reasons)


def test_probe_rejects_long_mesh_topology_port_contract(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    nodedef = (
        pack_config.parent
        / "json"
        / "BifrostScales"
        / "operators"
        / "bifrost_scales_nodedef.json"
    )
    data = json.loads(nodedef.read_text(encoding="utf-8"))
    for port in data["operators"][0]["ports"]:
        if port["portName"] in {"source_face_offset", "source_face_vertex", "face_offset", "face_vertex"}:
            port["portType"] = "array<long>"
    nodedef.write_text(json.dumps(data), encoding="utf-8")
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert status.ready is False
    assert status.rebuild_required is True
    assert status.mesh_topology_contract_valid is False
    assert any("array<uint>" in reason for reason in status.reasons)


def test_probe_rejects_mixed_legacy_json_library(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    pack_root = pack_config.parent
    legacy_root = pack_root / "json" / "BifrostScales"
    (legacy_root / "bifrost_scales_nodedef.json").write_text(
        '{"name":"BifrostScales::generate_scale_mesh_payload_arrays"}',
        encoding="utf-8",
    )
    (legacy_root / "BifrostScales_native_scales_v4_graph.json").write_text(
        "{}", encoding="utf-8"
    )
    (legacy_root / "manifest.bifrost-scales.json").write_text(
        '{"product":"not a Bifrost definition"}', encoding="utf-8"
    )
    pack_config.write_text(
        '{"AminoConfigurations":[{"jsonLibs":[{"path":"./json/BifrostScales","files":[]}]}]}',
        encoding="utf-8",
    )
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert status.definition_library_registered is False
    assert status.graph_library_registered is False
    assert status.pack_resources_isolated is False
    assert status.ready is False
    assert any("not isolated" in reason for reason in status.reasons)


def test_probe_finds_but_rejects_unregistered_nested_pack(tmp_path, monkeypatch):
    module_root = tmp_path / "modules" / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert Path(status.pack_config) == pack_config
    assert status.pack_config_available is True
    assert status.pack_config_registered is False
    assert status.ready is False
    assert any("not registered" in reason for reason in status.reasons)


def test_probe_requires_restart_when_module_changed_in_current_session(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.delenv("BIFROST_LIB_CONFIG_FILES", raising=False)

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds(False))

    assert status.pack_config_registered is True
    assert status.pack_config_active is False
    assert status.restart_required is True
    assert status.ready is False
    assert any("restart required" in reason.lower() for reason in status.reasons)


def test_probe_rejects_active_pack_missing_from_live_catalog(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds(False))

    assert status.pack_config_active is True
    assert status.catalog_query_available is True
    assert status.operator_definition_available is False
    assert status.restart_required is True
    assert status.ready is False
    assert any("node catalog" in reason.lower() for reason in status.reasons)

class FakeLegacyRuntimeCmds:
    def bifrostGraph(self, *args, **kwargs):
        del args, kwargs
        return None

    def vnn(self, **kwargs):
        if kwargs.get("runTimes"):
            return ["Amino", "Bifrost"]
        if kwargs.get("libraries") == "Amino":
            raise RuntimeError("not enumerable")
        if kwargs.get("libraries") == "Bifrost":
            return ["BrokenLibrary", "BifrostScales"]
        nodes = kwargs.get("nodes")
        if nodes in (["Bifrost", "BrokenLibrary"], ("Bifrost", "BrokenLibrary")):
            raise RuntimeError("broken third-party library")
        if nodes in (["Bifrost", "BifrostScales"], ("Bifrost", "BifrostScales")):
            return ["BifrostScales::generate_scale_mesh_payload_arrays"]
        raise RuntimeError("unknown runtime")


def test_catalog_probe_discovers_legacy_bifrost_runtime_and_continues_after_library_error():
    result = native_backend._operator_catalog_probe(FakeLegacyRuntimeCmds())
    assert result.query_available is True
    assert result.definition_available is True
    assert result.runtime == "Bifrost"
    assert result.library == "BifrostScales"
    assert result.match == "BifrostScales::generate_scale_mesh_payload_arrays"
    assert "broken third-party library" in result.error
    assert result.runtimes == ("Amino", "Bifrost")


def test_catalog_probe_accepts_comma_qualified_node_names():
    class CommaCatalog(FakeCatalogCmds):
        def vnn(self, **kwargs):
            if kwargs.get("runTimes"):
                return ["BifrostGraph"]
            if kwargs.get("libraries") == "BifrostGraph":
                return ["BifrostScales"]
            if kwargs.get("nodes"):
                return ["BifrostScales,generate_scale_mesh_payload_arrays"]
            return []

    result = native_backend._operator_catalog_probe(CommaCatalog())
    assert result.definition_available is True
    assert result.match == "BifrostScales,generate_scale_mesh_payload_arrays"


def test_catalog_probe_rejects_doubled_namespace_even_when_short_name_matches():
    result = native_backend._operator_catalog_probe(FakeDoubledNamespaceCmds())
    assert result.query_available is True
    assert result.definition_available is False
    assert result.namespace_exact is False
    assert result.namespace_duplicated is True
    assert result.library == "BifrostScales::BifrostScales"
    assert result.resolved_definition == (
        "BifrostScales::BifrostScales::generate_scale_mesh_payload_arrays"
    )


def test_catalog_probe_prefers_exact_namespace_when_old_and_new_packs_are_loaded():
    result = native_backend._operator_catalog_probe(FakeMixedNamespaceCmds())
    assert result.definition_available is True
    assert result.namespace_exact is True
    assert result.namespace_duplicated is False
    assert result.library == "BifrostScales"
    assert result.resolved_definition == (
        "BifrostScales::generate_scale_mesh_payload_arrays"
    )


def test_probe_marks_doubled_namespace_pack_for_clean_rebuild(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root)
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(
        cmds_module=FakeDoubledNamespaceCmds()
    )

    assert status.operator_definition_available is False
    assert status.catalog_namespace_exact is False
    assert status.catalog_namespace_duplicated is True
    assert status.rebuild_required is True
    assert status.restart_required is True
    assert status.ready is False
    assert any("doubled namespace" in reason for reason in status.reasons)


def test_native_graph_is_imported_and_world_mesh_connected_once_then_updates_payload_only(monkeypatch):
    cmds = FakeNativeCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-a",
    )

    graph = controller.create_graph(binding)
    assert graph == "nativeGraph1Shape"
    assert cmds.calls[0][1] == {"importGraphAsShape": "Graphs::BifrostScales::native_scales_v4"}
    assert cmds.calls[1] == (("nativeGraph1Shape",), {"enableAsync": False})
    assert cmds.calls[2] == (("nativeGraph1Shape",), {"runOnDemand": False})
    assert cmds.connect_calls == [
        ("targetShape.worldMesh[0]", "nativeGraph1Shape.source_mesh", True)
    ]
    assert cmds.connections["nativeGraph1Shape.source_mesh"] == "targetShape.worldMesh[0]"
    parent = cmds.nodes[graph]["parent"]
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphAsyncPolicy"] == "disabled"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphTargetPath"] == "/targetShape"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphTargetUuid"] == "uuid-targetShape"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphInputSuggestedType"] == "Object"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphSourcePlug"] == "targetShape.worldMesh[0]"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphBindingMode"] == "maya-dg-worldMesh"

    settings = ScaleSettings(target_count=32)
    first = controller.evaluate(binding, settings, GuideSet(), mode="settled")
    second = controller.evaluate(binding, settings, GuideSet(), mode="settled")
    assert first.success is True
    assert first.payload_changed is True
    assert first.scale_count == 32
    assert first.profile["schema"] == "bifrost-scales/native-profile/9"
    assert first.profile["orientation_ms"] == 2.0
    assert first.profile["orientation_prepare_ms"] == 0.4
    assert first.profile["direction_neighbors_ms"] == 0.3
    assert first.profile["direction_neighbors_cache_hit"] is True
    assert first.profile["direction_relax_ms"] == 0.8
    assert first.profile["direction_relax_pack_ms"] == 0.1
    assert first.profile["direction_relax_gpu_call_ms"] == 0.6
    assert first.profile["direction_relax_unpack_ms"] == 0.1
    assert first.profile["orientation_finalize_ms"] == 0.5
    assert second.payload_changed is False
    import_calls = [
        kwargs
        for _args, kwargs in cmds.calls
        if "importGraphAsShape" in kwargs
    ]
    assert len(cmds.connect_calls) == 1
    assert len(import_calls) == 1
    assert cmds.nodes[graph]["attrs"]["payload_json"].startswith("{")
    assert cmds.nodes["preview1"]["attrs"]["visibility"] is False
    assert cmds.nodes["nativeGraph1"]["attrs"]["visibility"] is True

    changed = controller.evaluate(
        binding,
        replace(settings, tip_offset=0.5),
        GuideSet(),
        mode="settled",
    )
    assert changed.payload_changed is True
    assert len(cmds.connect_calls) == 1

def test_native_graph_continues_when_enable_async_flag_is_unsupported(monkeypatch):
    cmds = FakeNoEnableAsyncCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-no-async-flag",
    )

    graph = controller.create_graph(binding)

    assert graph == "nativeGraph1Shape"
    parent = cmds.nodes[graph]["parent"]
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphAsyncPolicy"] == "unsupported"
    assert cmds.connections["nativeGraph1Shape.source_mesh"] == "targetShape.worldMesh[0]"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphTargetPath"] == "/targetShape"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphBindingMode"] == "maya-dg-worldMesh"
    assert cmds.nodes[parent]["attrs"]["bsNativeGraphEvaluationPolicy"] == (
        "run-on-demand-resumed"
    )


def test_async_stale_pre_binding_error_is_not_misreported_as_empty_mesh(monkeypatch):
    cmds = FakeAsyncStaleResultCmds()
    controller = NativeGraphController(
        cmds_module=cmds,
        evaluation_timeout_seconds=0.25,
        evaluation_poll_seconds=0.001,
    )
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-stale-async",
    )

    controller.create_graph(binding)
    evaluation = controller.evaluate(
        binding,
        ScaleSettings(target_count=32),
        GuideSet(),
        mode="settled",
    )

    assert evaluation.success is True
    assert evaluation.status == "ok"
    assert evaluation.scale_count == 32
    assert evaluation.execution_counter_before == 0
    assert evaluation.execution_counter_after == 1
    assert "execution-counter" in evaluation.evaluation_policy
    assert evaluation.execution_wait_ms >= 0.0


def test_counter_advance_from_pre_binding_run_is_not_accepted_as_latest(monkeypatch):
    cmds = FakeTwoStageAsyncCmds()
    controller = NativeGraphController(
        cmds_module=cmds,
        evaluation_timeout_seconds=0.25,
        evaluation_poll_seconds=0.001,
    )
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-two-stage-async",
    )

    controller.create_graph(binding)
    evaluation = controller.evaluate(
        binding,
        ScaleSettings(target_count=32),
        GuideSet(),
        mode="settled",
    )

    assert evaluation.success is True
    assert evaluation.execution_counter_before == 0
    assert evaluation.execution_counter_after == 2
    assert cmds.refresh_stage == 2


def test_async_wait_timeout_reports_stale_result_without_retrying(monkeypatch):
    cmds = FakeNeverPublishesCmds()
    controller = NativeGraphController(
        cmds_module=cmds,
        evaluation_timeout_seconds=0.02,
        evaluation_poll_seconds=0.001,
    )
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-never-publishes",
    )

    controller.create_graph(binding)
    with pytest.raises(RuntimeError, match="did not publish a fresh execution"):
        controller.evaluate(
            binding,
            ScaleSettings(target_count=32),
            GuideSet(),
            mode="settled",
        )

    payload_sets = [
        plug
        for plug, _value, _kwargs in getattr(cmds, "set_attr_calls", ())
        if plug.endswith(".payload_json")
    ]
    assert len(payload_sets) <= 1


def test_unexpected_async_policy_failure_still_rolls_back_new_graph(monkeypatch):
    cmds = FakeUnexpectedAsyncFailureCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-async-failure",
    )

    with pytest.raises(RuntimeError, match="execution policy is corrupt"):
        controller.create_graph(binding)

    assert not any(
        data.get("type") == "bifrostGraphShape"
        for data in cmds.nodes.values()
    )
    assert cmds.nodes["settings1"]["attrs"].get("bsNativeGraphPath", "") == ""


def test_existing_native_graph_without_verified_operator_stamp_is_rejected(monkeypatch):
    cmds = FakeNativeCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-old",
    )
    graph = controller.create_graph(binding)
    parent = cmds.nodes[graph]["parent"]
    cmds.nodes[parent]["attrs"].pop("bsNativeGraphOperatorDefinition", None)

    try:
        controller.evaluate(binding, ScaleSettings(target_count=8), GuideSet(), mode="settled")
    except RuntimeError as exc:
        assert "Delete the Native Graph" in str(exc)
    else:
        raise AssertionError("unstamped Native Graph was accepted")


def test_failed_graph_import_removes_only_graph_created_by_current_attempt(monkeypatch):
    class FailingImportCmds(FakeNativeCmds):
        def bifrostGraph(self, *args, **kwargs):
            if "importGraphAsShape" in kwargs:
                super().bifrostGraph(*args, **kwargs)
                raise RuntimeError("compile failed")
            return super().bifrostGraph(*args, **kwargs)

    cmds = FailingImportCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-fail",
    )

    try:
        controller.create_graph(binding)
    except RuntimeError as exc:
        assert "compile failed" in str(exc)
    else:
        raise AssertionError("failing graph import unexpectedly succeeded")

    assert not any(data["type"] == "bifrostGraphShape" for data in cmds.nodes.values())


def test_graph_v4_requires_typed_top_level_scene_input_contract(tmp_path):
    graph = tmp_path / "graph.json"
    source = Path(__file__).resolve().parents[1] / "BifrostScales" / "bifrost" / "compounds" / "BifrostScales_native_scales_v4_graph.json"
    graph.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    assert native_backend._graph_input_contract_valid(graph) is True

    data = json.loads(graph.read_text(encoding="utf-8"))
    data["compounds"][0]["metadata"] = [
        item for item in data["compounds"][0]["metadata"]
        if item.get("metaName") != "compoundIsGraph"
    ]
    graph.write_text(json.dumps(data), encoding="utf-8")
    assert native_backend._graph_input_contract_valid(graph) is False


def test_native_graph_creation_rejects_failed_world_mesh_connection(monkeypatch):
    class FailedConnectionCmds(FakeNativeCmds):
        def connectAttr(self, source, destination, force=False):
            self.connect_calls.append((source, destination, bool(force)))
            raise RuntimeError("incompatible Maya mesh connection")

    cmds = FailedConnectionCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-unresolved",
    )

    try:
        controller.create_graph(binding)
    except RuntimeError as exc:
        assert "Could not connect the Maya target mesh" in str(exc)
    else:
        raise AssertionError("failed worldMesh connection was accepted")

    assert not any(data["type"] == "bifrostGraphShape" for data in cmds.nodes.values())
    assert cmds.nodes["settings1"]["attrs"].get("bsNativeGraphPath", "") == ""


def test_native_graph_target_validation_rejects_severed_world_mesh_connection(monkeypatch):
    cmds = FakeNativeCmds()
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-severed",
    )

    graph = controller.create_graph(binding)
    cmds.connections.pop(graph + ".source_mesh", None)

    try:
        controller.evaluate(binding, ScaleSettings(target_count=8), GuideSet(), mode="settled")
    except RuntimeError as exc:
        assert "source_mesh is not connected" in str(exc)
    else:
        raise AssertionError("severed worldMesh connection was accepted")

def test_native_graph_creation_rejects_empty_target_before_import(monkeypatch):
    cmds = FakeNativeCmds()
    cmds.nodes["targetShape"]["vertices"] = 0
    controller = NativeGraphController(cmds_module=cmds)
    monkeypatch.setattr(controller, "probe", _ready_status)
    binding = SystemBinding(
        settings_node="settings1",
        target_mesh="targetShape",
        preview_transform="preview1",
        system_id="system-empty-target",
    )

    try:
        controller.create_graph(binding)
    except RuntimeError as exc:
        assert "has no polygon data" in str(exc)
    else:
        raise AssertionError("empty target was accepted")

    assert cmds.calls == []


def test_native_world_mesh_plug_comparison_normalizes_short_long_names_and_array_element():
    class PlugNameCmds:
        def ls(self, node=None, long=False, **_kwargs):
            if node in {"targetShape", "|group1|targetShape"} and long:
                return ["|group1|targetShape"]
            return [node] if node else []

    controller = NativeGraphController(cmds_module=PlugNameCmds())

    assert controller._plugs_equivalent(
        "|group1|targetShape.worldMesh[0]",
        "targetShape.worldMesh[0]",
    )
    assert controller._plugs_equivalent(
        "|group1|targetShape.worldMesh[0]",
        "targetShape.worldMesh",
    )
    assert not controller._plugs_equivalent(
        "|group1|targetShape.worldMesh[0]",
        "otherShape.worldMesh[0]",
    )


def test_probe_rejects_payload_schema_mismatch_even_when_pack_version_is_new_enough(
    tmp_path, monkeypatch
):
    modules = tmp_path / "modules"
    module_root = modules / "BifrostScales"
    pack_config = _write_nested_native_pack(module_root, version="0.10.7")
    pack_root = pack_config.parent
    graph = (
        pack_root
        / "json"
        / "BifrostScales"
        / "graphs"
        / "BifrostScales_native_scales_v4_graph.json"
    )
    graph_data = json.loads(graph.read_text(encoding="utf-8"))
    payload_port = next(
        port
        for port in graph_data["compounds"][0]["ports"]
        if port.get("portName") == "payload_json"
    )
    payload_default = json.loads(payload_port["portDefault"])
    payload_default["schema"] = "bifrost-scales/native-payload/6"
    payload_port["portDefault"] = json.dumps(
        payload_default,
        sort_keys=True,
        separators=(",", ":"),
    )
    graph.write_text(json.dumps(graph_data), encoding="utf-8")
    manifest = pack_root / "metadata" / "manifest.bifrost-scales.json"
    manifest.write_text(
        json.dumps({"native_payload_schema": "bifrost-scales/native-payload/6", "native_behavior_contract": "bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1"}),
        encoding="utf-8",
    )
    (modules / "BifrostScales.mod").write_text(
        "+ BifrostScales 0.9.0 {}\n"
        "PYTHONPATH +:= scripts\n"
        "BIFROST_LIB_CONFIG_FILES += {}\n".format(
            module_root.as_posix(),
            pack_config.as_posix(),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_backend, "_module_root", lambda: module_root)
    monkeypatch.setenv("BIFROST_LIB_CONFIG_FILES", str(pack_config))

    status = native_backend.probe_native_backend(cmds_module=FakeCatalogCmds())

    assert status.pack_version == "0.10.7"
    assert status.native_behavior_contract_valid is True
    assert status.payload_schema_contract_valid is False
    assert status.pack_graph_payload_schema == "bifrost-scales/native-payload/6"
    assert status.pack_manifest_payload_schema == "bifrost-scales/native-payload/6"
    assert status.ready is False
    assert status.rebuild_required is True
    assert any("payload schema" in reason.lower() for reason in status.reasons)


def test_native_profile_parser_rejects_invalid_or_unknown_payloads():
    assert native_backend._parse_native_profile(
        json.dumps(
            {
                "schema": "bifrost-scales/native-profile/9",
                "distribution_ms": 1.25,
                "cell_boundary_query_ms": 0.125,
                "cell_mean_neighbors": 63.5,
            }
        )
    )["distribution_ms"] == 1.25
    parsed = native_backend._parse_native_profile(
        json.dumps(
            {
                "schema": "bifrost-scales/native-profile/9",
                "cell_boundary_query_ms": 0.125,
                "cell_mean_neighbors": 63.5,
            }
        )
    )
    assert parsed["cell_boundary_query_ms"] == 0.125
    assert parsed["cell_mean_neighbors"] == 63.5
    assert native_backend._parse_native_profile("not-json") == {}
    assert native_backend._parse_native_profile(
        json.dumps({"schema": "bifrost-scales/native-profile/999"})
    ) == {}
