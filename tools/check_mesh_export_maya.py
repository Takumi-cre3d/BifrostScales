"""Isolated Maya test for native-output snapshot, source retention and Undo."""
import json
from pathlib import Path
import sys
import maya.standalone


def main():
    maya.standalone.initialize(name="python")
    try:
        from maya import cmds
        from maya.api import OpenMaya as om
        cmds.loadPlugin("bifrostGraph", quiet=True)
        installed = Path(cmds.moduleInfo(path=True, moduleName="BifrostScales"))
        source = Path(__file__).resolve().parents[1] / "BifrostScales/scripts"
        sys.path.insert(0, str(installed / "scripts" if "--installed" in sys.argv else source))
        from bifrost_scales.backend import NativeMayaBackend
        from bifrost_scales import native_backend
        from bifrost_scales.settings import ScaleSettings
        from bifrost_scales.sculpt_surface import normalize_surface
        if "--installed" not in sys.argv:
            native_backend._module_root = lambda: installed
        cmds.undoInfo(state=True)
        target = cmds.polyPlane(width=4, height=4, subdivisionsX=4, subdivisionsY=4)[0]
        cmds.setAttr(target + ".translate", 2, 3, 4, type="double3")
        backend = NativeMayaBackend()
        deltas = [(0., 0., 0.)] * 81
        deltas[40] = (.3, 0., .6)
        sculpt = normalize_surface(dict(schema="vector-surface/3", resolution=8, deltas=deltas))
        binding, report = backend.create_system_with_preview(target, ScaleSettings(target_count=24, sculpt_surface=sculpt))
        graph = backend.native_graph()
        # A saved pre-UV graph embeds its old wiring. Exercise the one-time upgrade.
        cmds.vnnConnect(graph, "/construct_mesh.mesh", "/output.out_mesh")
        parent = cmds.listRelatives(graph, parent=True, fullPath=True)[0]
        cmds.setAttr(parent + ".bsNativeGraphContract", "bifrost-scales/native-graph/4-dgmesh-1", type="string")
        before_uv_mesh = backend.create_maya_mesh()
        assert cmds.polyEvaluate(before_uv_mesh, uvcoord=True) == 0
        cmds.delete(before_uv_mesh)
        create_graph = backend.native.create_graph
        def fail_upgrade(*args):
            raise RuntimeError("Injected upgrade failure")
        backend.native.create_graph = fail_upgrade
        try:
            backend.bind(binding.settings_node)
            raise AssertionError("Expected upgrade failure")
        except RuntimeError as error:
            assert str(error) == "Injected upgrade failure"
            assert backend.native_graph() == graph and cmds.objExists(graph)
        finally:
            backend.native.create_graph = create_graph
        backend.bind(binding.settings_node)
        graph = backend.native_graph()
        assert "set_mesh_UVs" in cmds.vnnCompound(graph, "/", listNodes=True)
        payload = cmds.getAttr(graph + ".payload_json")
        connections = sorted(cmds.listConnections(graph, connections=True, plugs=True) or [])
        cmds.flushUndo()
        result = backend.create_maya_mesh()
        shape = cmds.listRelatives(result, shapes=True, fullPath=True)[0]
        assert cmds.polyEvaluate(shape, vertex=True) == report.vertex_count
        assert cmds.polyEvaluate(shape, face=True) == report.face_count
        assert not cmds.listConnections(shape + ".inMesh", source=True, destination=False)
        assert not cmds.ls(type="bifrostGeoToMaya")
        assert cmds.getAttr(graph + ".payload_json") == payload
        assert sorted(cmds.listConnections(graph, connections=True, plugs=True) or []) == connections
        selection = om.MSelectionList(); selection.add(shape)
        mesh = om.MFnMesh(selection.getDagPath(0))
        points = [(p.x, p.y, p.z) for p in mesh.getPoints(om.MSpace.kWorld)]
        assert min(p[1] for p in points) >= 3.0, "Target world-space translation was lost"
        topology = tuple(map(tuple, mesh.getVertices()))
        baseline = Path(__file__).resolve().parents[1] / "native/build/uv-geometry-baseline.json"
        geometry = dict(points=points, topology=topology)
        if "--capture" in sys.argv:
            baseline.write_text(json.dumps(geometry), encoding="utf-8")
        elif baseline.exists():
            assert json.loads(baseline.read_text()) == json.loads(json.dumps(geometry)), "Geometry changed"
        def check_uvs(fn):
            u, v = fn.getUVs()
            assert len(u), "Missing UVs"
            counts, ids = fn.getAssignedUVs()
            assert sum(counts) == len(fn.getVertices()[1]), "Unassigned face UVs"
            offset = 0
            for count in counts:
                face = ids[offset:offset+count]
                area = sum(u[face[i]]*v[face[(i+1)%count]]-u[face[(i+1)%count]]*v[face[i]] for i in range(count))
                assert area > -1e-8, "Mirrored UV face"
                offset += count
            shells, shell_ids = fn.getUvShellsIds()
            bounds = [[1., 1., 0., 0.] for _ in range(shells)]
            for index, shell in enumerate(shell_ids):
                b = bounds[shell]
                b[0]=min(b[0],u[index]); b[1]=min(b[1],v[index])
                b[2]=max(b[2],u[index]); b[3]=max(b[3],v[index])
            assert all(all(abs(a-b)<1e-6 for a,b in zip(bound,(0,0,1,1))) for bound in bounds), bounds
            return shells
        assert check_uvs(mesh) == report.scale_count
        cmds.undo()
        assert not cmds.objExists(result) and cmds.objExists(graph)
        cmds.redo()
        assert cmds.objExists(result) and cmds.objExists(graph)
        backend.delete_system()
        assert cmds.objExists(result)
        selection = om.MSelectionList(); selection.add(shape)
        mesh = om.MFnMesh(selection.getDagPath(0))
        assert points == [(p.x, p.y, p.z) for p in mesh.getPoints(om.MSpace.kWorld)]
        assert topology == tuple(map(tuple, mesh.getVertices()))
        del mesh, selection
        cmds.file(new=True, force=True)
        cmds.flushUndo()
        print(json.dumps(dict(status="PASS", vertices=len(points), faces=report.face_count,
                              undo_redo=True, source_independent=True, per_scale_uvs=True, uv_not_mirrored=True)), flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        raise
    finally:
        mesh = selection = None
        from maya import cmds
        cmds.file(new=True, force=True)
        cmds.flushUndo()
        maya.standalone.uninitialize()


if __name__ == "__main__":
    main()
