from types import SimpleNamespace

import bifrost_scales.native_smoke as native_smoke
from bifrost_scales.settings import ScaleSettings


class FakeStatus:
    def __init__(self, ready=True):
        self.ready = bool(ready)
        self.reasons = () if ready else ("native unavailable",)

    def to_mapping(self):
        return {"ready": self.ready, "reasons": self.reasons}


class FakeCmds:
    def __init__(self):
        self.nodes = set()
        self.created_planes = []
        self.deleted = []

    def polyPlane(self, **kwargs):
        del kwargs
        name = "bifrostScalesNativeSmokeTarget1"
        self.nodes.add(name)
        self.created_planes.append(name)
        return [name, name + "Poly"]

    def objExists(self, node):
        return node in self.nodes

    def delete(self, node):
        self.deleted.append(node)
        self.nodes.discard(node)


class FakeBackend:
    def __init__(self, systems=(), ready=True):
        self.systems = list(systems)
        self.status = FakeStatus(ready=ready)
        self.binding = None
        self.created_systems = []
        self.bound = []
        self.graph_created = False
        self.graph_deleted = False
        self.system_deleted = False
        self.preview_backend = "native"
        self.settings = ScaleSettings(
            target_count=32,
            settled_budget=32,
            interactive_budget=16,
        )

    def native_status(self):
        return self.status

    def list_systems(self):
        return list(self.systems)

    def create_system(self, target, settings):
        assert isinstance(settings, ScaleSettings)
        node = "bifrostScalesSettingsSmoke1"
        self.systems.append(node)
        self.created_systems.append((target, settings))
        self.binding = SimpleNamespace(settings_node=node)
        self.settings = settings
        return self.binding

    def bind(self, settings_node):
        self.bound.append(settings_node)
        self.binding = SimpleNamespace(settings_node=settings_node)
        return self.binding

    def create_native_graph(self):
        self.graph_created = True
        return "bifrostScalesNativeSmokeGraphShape1"

    def set_preview_backend(self, mode):
        self.preview_backend = mode
        return mode

    def read_settings(self):
        return self.settings

    def apply(self, request):
        assert request.snapshot["target_count"] == 32
        return SimpleNamespace(
            scale_count=32,
            vertex_count=256,
            face_count=224,
            mesh_update="native-payload",
            total_ms=12.5,
            native_execution_wait_ms=7.5,
            native_execution_counter_before=4,
            native_execution_counter_after=5,
            native_evaluation_policy="run-on-demand-resumed+execution-counter",
        )

    def delete_native_graph(self):
        self.graph_deleted = True
        return True

    def delete_system(self):
        self.system_deleted = True
        self.binding = None


def _install_backend(monkeypatch, backend):
    monkeypatch.setattr(
        native_smoke,
        "NativeMayaBackend",
        lambda cmds_module=None, om_module=None: backend,
    )


def test_probe_only_is_read_only(monkeypatch):
    backend = FakeBackend()
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(evaluate=False, cmds_module=cmds)

    assert result["success"] is True
    assert result["phase"] == "probe"
    assert cmds.created_planes == []
    assert backend.created_systems == []


def test_evaluate_auto_creates_and_retains_test_system_when_graph_is_retained(monkeypatch):
    backend = FakeBackend()
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(
        evaluate=True,
        cleanup_graph=False,
        cmds_module=cmds,
    )

    assert result["success"] is True
    assert result["phase"] == "evaluate"
    assert result["auto_created_system"] is True
    assert result["temporary_system_retained"] is True
    assert result["settings_node"] == "bifrostScalesSettingsSmoke1"
    assert result["scale_count"] == 32
    assert result["native_execution_wait_ms"] == 7.5
    assert result["native_execution_counter_before"] == 4
    assert result["native_execution_counter_after"] == 5
    assert result["native_evaluation_policy"] == (
        "run-on-demand-resumed+execution-counter"
    )
    assert backend.graph_created is True
    assert backend.preview_backend == "native"
    assert backend.system_deleted is False
    assert cmds.created_planes == ["bifrostScalesNativeSmokeTarget1"]
    assert cmds.deleted == []


def test_evaluate_cleans_auto_created_system_when_graph_cleanup_is_requested(monkeypatch):
    backend = FakeBackend()
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(
        evaluate=True,
        cleanup_graph=True,
        cmds_module=cmds,
    )

    assert result["success"] is True
    assert result["auto_created_system"] is True
    assert result["test_system_cleaned"] is True
    assert result["test_target_cleaned"] is True
    assert result["graph_cleaned"] is True
    assert backend.system_deleted is True
    assert cmds.deleted == ["bifrostScalesNativeSmokeTarget1"]


def test_existing_system_is_used_without_creating_test_geometry(monkeypatch):
    backend = FakeBackend(systems=("existingSettings1",))
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(
        evaluate=True,
        cleanup_graph=True,
        cmds_module=cmds,
    )

    assert result["success"] is True
    assert result["auto_created_system"] is False
    assert result["settings_node"] == "existingSettings1"
    assert backend.bound[0] == "existingSettings1"
    assert backend.graph_deleted is True
    assert backend.system_deleted is False
    assert cmds.created_planes == []


def test_auto_create_can_be_disabled_with_actionable_error(monkeypatch):
    backend = FakeBackend()
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(
        evaluate=True,
        auto_create_system=False,
        cmds_module=cmds,
    )

    assert result["success"] is False
    assert result["phase"] == "setup"
    assert "auto_create_system=True" in result["error"]
    assert cmds.created_planes == []


def test_unavailable_native_pack_does_not_modify_scene(monkeypatch):
    backend = FakeBackend(ready=False)
    cmds = FakeCmds()
    _install_backend(monkeypatch, backend)

    result = native_smoke.run(evaluate=True, cmds_module=cmds)

    assert result["success"] is False
    assert result["phase"] == "probe"
    assert result["error"] == "native unavailable"
    assert cmds.created_planes == []
