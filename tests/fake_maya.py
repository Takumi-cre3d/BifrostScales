from __future__ import annotations

from collections import defaultdict


class FakeCmds:
    def __init__(self):
        self.nodes = {}
        self.connections = {}
        self.counters = defaultdict(int)
        self.selection = []
        self.cv_points = {}
        self.contexts = {}
        self.current_context = "selectSuperContext"
        self.refresh_count = 0
        self.undo_enabled = True
        self.undo_chunk_depth = 0
        self.undo_events = []
        self.deferred_calls = []

    def _split(self, plug):
        node, attr = plug.rsplit(".", 1)
        return node, attr

    def _unique(self, name):
        if "#" in name:
            base = name.replace("#", "")
            self.counters[base] += 1
            return base + str(self.counters[base])
        if name not in self.nodes:
            return name
        self.counters[name] += 1
        return name + str(self.counters[name])

    def createNode(self, node_type, name, parent=None):
        name = self._unique(name)
        self.nodes[name] = {
            "type": node_type,
            "attrs": {
                "message": None,
                "visibility": True,
                "intermediateObject": False,
                "translateX": 0.0,
                "translateY": 0.0,
                "translateZ": 0.0,
            },
            "parent": parent,
            "children": [],
            "matrix": [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ],
        }
        if parent:
            self.nodes[parent]["children"].append(name)
        return name

    def spaceLocator(self, name):
        transform = self.createNode("transform", name)
        self.createNode("locator", transform + "Shape", parent=transform)
        return [transform]

    def curve(
        self,
        curve=None,
        point=None,
        p=None,
        degree=1,
        name="curve#",
        replace=False,
        r=False,
        worldSpace=False,
        **kwargs,
    ):
        del degree, worldSpace, kwargs
        points = point if point is not None else p
        points = [tuple(float(value) for value in item[:3]) for item in (points or [])]
        replacing = bool(replace or r)
        if replacing:
            if not curve or curve not in self.nodes:
                raise ValueError("curve does not exist")
            transform = str(curve)
            shapes = self.listRelatives(transform, shapes=True, type="nurbsCurve") or []
            if not shapes:
                raise ValueError("node is not a curve")
            self.cv_points[shapes[0]] = list(points)
            return transform
        transform = self.createNode("transform", name)
        shape = self.createNode("nurbsCurve", transform + "Shape", parent=transform)
        self.cv_points[shape] = list(points)
        return transform

    def draggerContext(
        self,
        name=None,
        query=False,
        edit=False,
        exists=False,
        **kwargs,
    ):
        name = str(name or "draggerContext#")
        if exists:
            return name in self.contexts
        if query:
            data = self.contexts[name]
            if kwargs.get("anchorPoint"):
                return data.get("anchorPoint", (0.0, 0.0, 0.0))
            if kwargs.get("dragPoint"):
                return data.get("dragPoint", (0.0, 0.0, 0.0))
            return None
        if edit:
            self.contexts.setdefault(name, {}).update(kwargs)
            return name
        self.contexts[name] = dict(kwargs)
        self.contexts[name].setdefault("anchorPoint", (0.0, 0.0, 0.0))
        self.contexts[name].setdefault("dragPoint", (0.0, 0.0, 0.0))
        return name

    def currentCtx(self):
        return self.current_context

    def setToolTo(self, name):
        previous = self.current_context
        self.current_context = str(name)
        if previous != self.current_context and previous in self.contexts:
            callback = self.contexts[previous].get("finalize")
            if callable(callback):
                callback()
        return self.current_context

    def deleteUI(self, name, **kwargs):
        del kwargs
        self.contexts.pop(str(name), None)

    def evalDeferred(self, callback, **kwargs):
        del kwargs
        self.deferred_calls.append(callback)

    def run_deferred(self):
        while self.deferred_calls:
            callback = self.deferred_calls.pop(0)
            callback()

    def refresh(self, **kwargs):
        del kwargs
        self.refresh_count += 1

    def set_context_point(self, name, anchor=None, drag=None):
        context = self.contexts[str(name)]
        if anchor is not None:
            context["anchorPoint"] = tuple(anchor)
        if drag is not None:
            context["dragPoint"] = tuple(drag)

    def trigger_context(self, name, event):
        mapping = {
            "press": "pressCommand",
            "drag": "dragCommand",
            "release": "releaseCommand",
            "finalize": "finalize",
        }
        callback = self.contexts[str(name)].get(mapping[event])
        if callable(callback):
            return callback()
        return None

    def objExists(self, node):
        return node in self.nodes

    def nodeType(self, node):
        return self.nodes[node]["type"]

    def addAttr(self, node, longName, attributeType=None, dataType=None):
        self.nodes[node]["attrs"][longName] = None

    def attributeQuery(self, name, node, exists=False):
        assert exists
        return name in self.nodes[node]["attrs"]

    def setAttr(self, plug, *values, **kwargs):
        node, attr = self._split(plug)
        value = values[0] if len(values) == 1 else tuple(values)
        self.nodes[node]["attrs"][attr] = value
        if attr in {"translateX", "translateY", "translateZ"}:
            index = {"translateX": 12, "translateY": 13, "translateZ": 14}[attr]
            self.nodes[node]["matrix"][index] = float(value)

    def getAttr(self, plug):
        node, attr = self._split(plug)
        return self.nodes[node]["attrs"].get(attr)

    def connectAttr(self, source, destination, force=False):
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

    def ls(self, pattern=None, type=None, selection=False, long=False, flatten=False, **kwargs):
        del long, kwargs
        if selection:
            return list(self.selection)
        if pattern and ".cv[*]" in str(pattern):
            shape = str(pattern).split(".cv[*]", 1)[0]
            return ["{}.cv[{}]".format(shape, index) for index in range(len(self.cv_points.get(shape, ())))]
        if pattern is not None:
            candidate = str(pattern)
            if candidate not in self.nodes:
                return []
            if type is not None and self.nodes[candidate]["type"] != type:
                return []
            return [candidate]
        if type is None:
            return list(self.nodes)
        return [name for name, data in self.nodes.items() if data["type"] == type]

    def select(self, values=None, replace=False, clear=False, **kwargs):
        del kwargs
        if clear:
            self.selection = []
            return
        if values is None:
            return
        items = [values] if isinstance(values, str) else list(values)
        if replace:
            self.selection = items
        else:
            self.selection.extend(items)

    def listRelatives(
        self,
        node,
        shapes=False,
        noIntermediate=False,
        fullPath=False,
        type=None,
        parent=False,
        children=False,
        allDescendents=False,
        **kwargs,
    ):
        del noIntermediate, fullPath, kwargs
        if parent:
            value = self.nodes[node]["parent"]
            return [value] if value else []
        values = list(self.nodes[node]["children"])
        if allDescendents:
            queue = list(values)
            values = []
            while queue:
                item = queue.pop(0)
                values.append(item)
                queue.extend(self.nodes[item]["children"])
        if shapes:
            values = [value for value in values if self.nodes[value]["type"] != "transform"]
        elif children:
            pass
        if type is not None:
            values = [value for value in values if self.nodes[value]["type"] == type]
        return values

    def delete(self, values, **kwargs):
        del kwargs
        if isinstance(values, str):
            values = [values]
        for node in list(values):
            self._delete_one(node)

    def _delete_one(self, node):
        if node not in self.nodes:
            return
        for child in list(self.nodes[node]["children"]):
            self._delete_one(child)
        parent = self.nodes[node]["parent"]
        if parent and parent in self.nodes and node in self.nodes[parent]["children"]:
            self.nodes[parent]["children"].remove(node)
        self.connections = {
            destination: source
            for destination, source in self.connections.items()
            if destination.rsplit(".", 1)[0] != node and source.rsplit(".", 1)[0] != node
        }
        self.selection = [item for item in self.selection if item != node]
        self.cv_points.pop(node, None)
        self.nodes.pop(node, None)

    def deleteAttr(self, plug):
        node, attr = self._split(plug)
        self.nodes[node]["attrs"].pop(attr, None)

    def duplicate(self, node, name, returnRootsOnly=True):
        del returnRootsOnly
        duplicate = self.createNode(self.nodes[node]["type"], name)
        self.nodes[duplicate]["attrs"].update(dict(self.nodes[node]["attrs"]))
        self.nodes[duplicate]["matrix"] = list(self.nodes[node]["matrix"])
        for child in self.nodes[node]["children"]:
            copied = self.createNode(
                self.nodes[child]["type"],
                child + "Copy",
                parent=duplicate,
            )
            self.nodes[copied]["attrs"].update(dict(self.nodes[child]["attrs"]))
            if child in self.cv_points:
                self.cv_points[copied] = list(self.cv_points[child])
        return [duplicate]

    def parent(self, node, parent=None, world=False, **kwargs):
        del kwargs
        old_parent = self.nodes[node]["parent"]
        if old_parent and node in self.nodes[old_parent]["children"]:
            self.nodes[old_parent]["children"].remove(node)
        new_parent = None if world else parent
        self.nodes[node]["parent"] = new_parent
        if new_parent and node not in self.nodes[new_parent]["children"]:
            self.nodes[new_parent]["children"].append(node)
        return [node]

    def xform(
        self,
        node,
        query=False,
        worldSpace=False,
        translation=False,
        matrix=False,
        **kwargs,
    ):
        del worldSpace, kwargs
        if query:
            if translation:
                value = self.nodes[node]["matrix"]
                return [value[12], value[13], value[14]]
            if matrix:
                return list(self.nodes[node]["matrix"])
            return None
        if translation is not False:
            values = translation
            self.nodes[node]["matrix"][12:15] = [float(values[0]), float(values[1]), float(values[2])]
            self.nodes[node]["attrs"]["translateX"] = float(values[0])
            self.nodes[node]["attrs"]["translateY"] = float(values[1])
            self.nodes[node]["attrs"]["translateZ"] = float(values[2])
        if matrix is not False:
            self.nodes[node]["matrix"] = list(matrix)
        return None

    def exactWorldBoundingBox(self, node):
        del node
        return [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]

    def pointPosition(self, component, world=False):
        del world
        shape, raw_index = component.rsplit(".cv[", 1)
        index = int(raw_index.rstrip("]"))
        return self.cv_points[shape][index]

    def undoInfo(
        self,
        query=False,
        state=False,
        stateWithoutFlush=None,
        openChunk=False,
        closeChunk=False,
        chunkName=None,
        **kwargs,
    ):
        del kwargs
        if query and state:
            return self.undo_enabled
        if stateWithoutFlush is not None:
            self.undo_enabled = bool(stateWithoutFlush)
            self.undo_events.append(("state", self.undo_enabled))
        if openChunk:
            self.undo_chunk_depth += 1
            self.undo_events.append(("open", str(chunkName or "")))
        if closeChunk:
            self.undo_chunk_depth = max(0, self.undo_chunk_depth - 1)
            self.undo_events.append(("close", ""))
        return None
