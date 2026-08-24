from types import SimpleNamespace

import pytest

from bifrost_scales.backend import NativeMayaBackend
from bifrost_scales.guides import GuideSet
from bifrost_scales.native_backend import NativeGraphEvaluation
from bifrost_scales.scene import SystemBinding
from bifrost_scales.settings import ScaleSettings


class FakeScene:
    def __init__(self):
        self.cmds = SimpleNamespace(objExists=lambda _node: False)
        self.created = []
        self.deleted = []
        self.written = []
        self.stats = []
        self._binding = None

    def create_system(self, target_mesh, settings):
        binding = SystemBinding(
            settings_node="settings1",
            target_mesh=str(target_mesh),
            preview_transform="preview1",
            system_id="system-1",
            guide_root="guides1",
        )
        self._binding = binding
        self.created.append((str(target_mesh), settings))
        return binding

    def bind(self, settings_node):
        assert self._binding is not None
        assert settings_node == self._binding.settings_node
        return self._binding

    def delete_system(self, settings_node):
        self.deleted.append(settings_node)
        self._binding = None

    def read_guides(self, settings_node):
        assert settings_node == "settings1"
        return GuideSet()

    def guide_management_fingerprint(self, settings_node):
        assert settings_node == "settings1"
        return ()

    def write_settings(self, settings_node, settings):
        self.written.append((settings_node, settings))

    def set_stats(self, preview_transform, scales, points, faces):
        self.stats.append((preview_transform, scales, points, faces))

    def selected_mesh(self):
        return "selectedMeshShape"


class FakeNative:
    def __init__(self, *, ready=True, fail_create=False, fail_evaluate=False):
        self.ready = ready
        self.fail_create = fail_create
        self.fail_evaluate = fail_evaluate
        self.created = []
        self.deleted = []
        self.active = []
        self.evaluated = []

    def probe(self):
        return SimpleNamespace(
            ready=self.ready,
            reasons=() if self.ready else ("native unavailable",),
        )

    def create_graph(self, binding):
        if self.fail_create:
            raise RuntimeError("graph create failed")
        self.created.append(binding.settings_node)
        return "nativeGraphShape1"

    def delete_graph(self, binding):
        self.deleted.append(binding.settings_node)
        return True

    def set_active(self, binding, *, active, visible):
        self.active.append((binding.settings_node, bool(active), bool(visible)))

    def evaluate(self, binding, settings, guides, *, mode, display_only=False, **_kwargs):
        if self.fail_evaluate:
            raise RuntimeError("native evaluation failed")
        self.evaluated.append(
            (binding.settings_node, settings, guides, mode, bool(display_only))
        )
        return NativeGraphEvaluation(
            graph_shape="nativeGraphShape1",
            graph_parent="nativeGraph1",
            success=True,
            status="ok",
            scale_count=64,
            point_count=640,
            face_count=576,
            payload_changed=True,
            generation_ms=12.0,
            viewport_ms=3.0,
            total_ms=15.0,
            execution_wait_ms=2.0,
            execution_counter_before=4,
            execution_counter_after=5,
            evaluation_policy="run-on-demand",
            profile={"operator_total_ms": 10.0},
        )


def backend_with(scene, native):
    backend = NativeMayaBackend.__new__(NativeMayaBackend)
    backend.scene = scene
    backend.native = native
    backend._binding = None
    backend._guide_cache = None
    backend._guide_management_cache = None
    return backend


def test_native_only_backend_rejects_python_preview():
    backend = backend_with(FakeScene(), FakeNative())
    assert backend.preview_backend == "native"
    assert backend.PREVIEW_BACKENDS == ("native",)
    with pytest.raises(ValueError, match="Python Reference preview was removed"):
        backend.set_preview_backend("python")


def test_create_system_builds_graph_and_completes_first_native_preview():
    scene = FakeScene()
    native = FakeNative()
    backend = backend_with(scene, native)
    settings = ScaleSettings(target_count=64, settled_budget=64)

    binding, report = backend.create_system_with_preview(
        "targetShape",
        settings,
        mode="settled",
    )

    assert binding.settings_node == "settings1"
    assert native.created == ["settings1"]
    assert native.active == [("settings1", True, True)]
    assert len(native.evaluated) == 1
    assert native.evaluated[0][3] == "settled"
    assert report.scale_count == 64
    assert report.vertex_count == 640
    assert report.face_count == 576
    assert report.mesh_update == "native-payload"
    assert scene.stats == [("preview1", 64, 640, 576)]


def test_create_system_rolls_back_scene_when_graph_creation_fails():
    scene = FakeScene()
    native = FakeNative(fail_create=True)
    backend = backend_with(scene, native)

    with pytest.raises(RuntimeError, match="graph create failed"):
        backend.create_system("targetShape", ScaleSettings())

    assert scene.deleted == ["settings1"]
    assert backend.binding is None


def test_create_system_with_preview_rolls_back_when_first_evaluation_fails():
    scene = FakeScene()
    native = FakeNative(fail_evaluate=True)
    backend = backend_with(scene, native)

    with pytest.raises(RuntimeError, match="native evaluation failed"):
        backend.create_system_with_preview("targetShape", ScaleSettings())

    assert native.created == ["settings1"]
    assert native.deleted == ["settings1"]
    assert scene.deleted == ["settings1"]
    assert backend.binding is None


def test_create_system_refuses_to_modify_scene_when_native_pack_is_unavailable():
    scene = FakeScene()
    backend = backend_with(scene, FakeNative(ready=False))

    with pytest.raises(RuntimeError, match="native unavailable"):
        backend.create_system("targetShape", ScaleSettings())

    assert scene.created == []
