"""Export one Maya Native Graph as parity_dump OBJ and payload inputs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    os.environ["MAYA_SKIP_USERSETUP_PY"] = "1"
    import maya.standalone

    maya.standalone.initialize(name="python")
    import maya.api.OpenMaya as om
    import maya.cmds as cmds

    cmds.loadPlugin("bifrostGraph", quiet=True)
    cmds.file(
        str(arguments.scene.resolve()),
        open=True,
        force=True,
        prompt=False,
        ignoreVersion=True,
        executeScriptNodes=False,
        loadReferenceDepth="none",
    )
    matches = cmds.ls(arguments.graph, long=True) or []
    if len(matches) != 1:
        raise RuntimeError(
            f"--graph must resolve to exactly one node; found {len(matches)}"
        )
    graph = matches[0]
    payload = cmds.getAttr(graph + ".payload_json") or ""
    json.loads(payload)
    sources = cmds.listConnections(
        graph + ".source_mesh",
        source=True,
        destination=False,
        shapes=True,
    ) or []
    if len(sources) != 1:
        raise RuntimeError(
            f"{graph}.source_mesh must have exactly one source; found {len(sources)}"
        )

    selection = om.MSelectionList()
    selection.add(sources[0])
    mesh = om.MFnMesh(selection.getDagPath(0))
    points = mesh.getPoints(om.MSpace.kWorld)
    _, triangle_vertices = mesh.getTriangles()

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = arguments.output_dir / "target.obj"
    payload_path = arguments.output_dir / "payload.json"
    with mesh_path.open("w", encoding="utf-8", newline="\n") as output:
        for point in points:
            output.write(f"v {point.x:.17g} {point.y:.17g} {point.z:.17g}\n")
        for index in range(0, len(triangle_vertices), 3):
            a, b, c = triangle_vertices[index : index + 3]
            output.write(f"f {a + 1} {b + 1} {c + 1}\n")
    payload_path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "graph": graph,
                "source": sources[0],
                "vertices": len(points),
                "triangles": len(triangle_vertices) // 3,
                "payload_bytes": len(payload.encode("utf-8")),
                "mesh": str(mesh_path.resolve()),
                "payload": str(payload_path.resolve()),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Bifrost 2.15 can access Python after mayapy releases the GIL at shutdown.
    os._exit(exit_code)
