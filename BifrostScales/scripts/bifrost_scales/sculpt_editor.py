"""Maya authoring mesh; optional settled-stroke apply, never while brushing."""

import json
from contextlib import contextmanager

from .qt_compat import QtCore, QtGui, QtWidgets
from .i18n import translate_window
from .ui_theme import STUDIO_STYLE
from .sculpt_surface import ZERO_CURVE, normalize_surface, editor_points, editor_rest_point, capture_surface


@contextmanager
def viewport_undo_disabled():
    """Transient camera, filter and brush-selection changes are not scene edits."""
    from maya import cmds
    enabled = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        yield
    finally:
        cmds.undoInfo(stateWithoutFlush=enabled)


def grid_faces(n, triangles=False):
    result = []
    for j in range(n):
        for i in range(n):
            a = j*(n+1)+i
            b, c, d = a+n+1, a+n+2, a+1
            result.extend((a,b,c,a,c,d) if triangles else (a,b,c,d))
    return result


class SculptEditor(QtWidgets.QDialog):
    def __init__(self, surface, apply, parent=None, owner_key=""):
        super().__init__(parent)
        self.setStyleSheet(STUDIO_STYLE)
        self.setWindowTitle("Interior Sculpt — 編集用パッチ")
        self.surface = normalize_surface(surface or {"schema": "vector-surface/3"})
        self.apply_surface = apply
        self.mesh = None
        self.disk = True
        self.owner_key = owner_key
        self.panel = self.host = self.camera = self.direction_marker = self.view_filter = None
        self.filters = []
        self.scene_callbacks = []
        self.previous_selection = self.previous_tool = None
        self.brush_command = None
        self.editing = False
        self._stroke = False
        self._pending_apply = False
        self._last_applied = None
        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(250)
        self._apply_timer.timeout.connect(self.auto_commit)
        self.resize(640, 650)
        layout = QtWidgets.QVBoxLayout(self)
        notice = QtWidgets.QLabel("黄色の矢印が前方（+V）です。内側をスカルプト → 適用して元のビューで確認。外周・Gapは保持します。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.resolution = QtWidgets.QComboBox()
        for n in sorted({32, 64, 128, self.surface["resolution"]}):
            self.resolution.addItem(str(n), n)
        self.resolution.setCurrentIndex(self.resolution.findData(self.surface["resolution"]))
        self.resolution.setEnabled(not bool(self.surface["deltas"]))
        toolbar = QtWidgets.QHBoxLayout()
        layout.addLayout(toolbar)
        self.brushes = QtWidgets.QButtonGroup(self)
        self.brushes.setExclusive(True)
        for label, command, icon in (
            ("盛る / Sculpt", "SetMeshSculptTool", "Sculpt.png"),
            ("つかむ / Grab — 3方向", "SetMeshGrabTool", "Grab.png"),
            ("滑らかに / Smooth", "SetMeshSmoothTool", "Smooth.png"),
        ):
            button = QtWidgets.QToolButton()
            button.setIcon(QtGui.QIcon(":/" + icon))
            button.setIconSize(QtCore.QSize(32, 32))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, c=command: self.choose_brush(c))
            self.brushes.addButton(button)
            toolbar.addWidget(button)
        self.brushes.buttons()[0].setChecked(True)
        self.brush_command = "SetMeshSculptTool"
        toolbar.addStretch()
        toolbar.addWidget(QtWidgets.QLabel("分割数"))
        toolbar.addWidget(self.resolution)
        menu_button = QtWidgets.QToolButton()
        menu_button.setText("⋯")
        menu_button.setToolTip("パッチ操作")
        menu_button.setAccessibleName("パッチ操作")
        menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(menu_button)
        for label, callback in (
            ("新規パッチ（分割数を指定）…", self.new_patch),
            ("選択中の編集パッチを再開", self.resume),
            ("パッチ全体を表示", self.frame),
            ("保存先の立体編集を解除（TypeはGlobalに戻る）", self.reset_surface),
        ):
            menu.addAction(label, lambda checked=False, action=callback: self.run(action))
        menu_button.setMenu(menu)
        toolbar.addWidget(menu_button)
        self.viewport = QtWidgets.QVBoxLayout()
        layout.addLayout(self.viewport, 1)
        footer = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("手動反映 · ドラフトは閉じても保持されます")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.auto_apply = QtWidgets.QCheckBox("ストローク後に適用")
        self.auto_apply.setToolTip("操作が止まってから変更を反映します。重いSystemではOFFにしてください。")
        self.auto_apply.toggled.connect(self.auto_apply_changed)
        footer.addWidget(self.auto_apply)
        button = QtWidgets.QPushButton("適用")
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self.run(self.commit))
        footer.addWidget(button)
        layout.addLayout(footer)
        translate_window(self)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.panel:
            self.run(self.open_view)

    @viewport_undo_disabled()
    def open_view(self):
        from maya import cmds, OpenMayaUI
        from maya.api import OpenMaya as om
        try:
            from shiboken6 import wrapInstance
        except ImportError:
            from shiboken2 import wrapInstance
        self.previous_selection = om.MGlobal.getActiveSelectionList()
        self.previous_tool = cmds.currentCtx()
        if not self.mesh and self.owner_key:
            drafts = [node for node in cmds.ls("*.bifrostSculptOwner", objectsOnly=True, long=True) or []
                      if cmds.getAttr(node+".bifrostSculptOwner") == self.owner_key]
            if len(drafts) > 1:
                raise ValueError("同じ保存先のドラフトが複数あります。メニューから選択して再開してください。")
            if drafts:
                cmds.select(drafts[0], replace=True)
                self.resume()
        self.create_or_update()
        self.direction_marker = cmds.curve(
            degree=1,
            point=((0, .012, .34), (0, .012, .70), (-.10, .012, .57),
                   (0, .012, .70), (.10, .012, .57)),
            name="BifrostScales_SculptForward#",
        )
        cmds.setAttr(self.direction_marker + ".overrideEnabled", True)
        cmds.setAttr(self.direction_marker + ".overrideColor", 17)
        cmds.setAttr(self.direction_marker + ".overrideDisplayType", 2)
        marker_nodes = [self.direction_marker] + cmds.listRelatives(
            self.direction_marker, shapes=True, fullPath=True
        )
        for node in marker_nodes:
            selection = om.MSelectionList()
            selection.add(node)
            om.MFnDependencyNode(selection.getDependNode(0)).setDoNotWrite(True)
        self.camera = cmds.camera(name="BifrostScales_SculptCamera#")[0]
        for node in [self.camera] + cmds.listRelatives(self.camera, shapes=True, fullPath=True):
            selection = om.MSelectionList()
            selection.add(node)
            om.MFnDependencyNode(selection.getDependNode(0)).setDoNotWrite(True)
        cmds.setAttr(self.camera+".translate", 0, 1.6, 1.6, type="double3")
        cmds.setAttr(self.camera+".rotateX", -45)
        self.host = cmds.window()
        pane = cmds.paneLayout(parent=self.host)
        # A standalone modelEditor has no modelPanel bar callbacks. Reparenting a
        # full modelPanel makes Maya build invalid `||modelPanel...` UI paths.
        self.panel = cmds.modelEditor(parent=pane, camera=self.camera)
        control = cmds.modelEditor(self.panel, query=True, control=True)
        pointer = OpenMayaUI.MQtUtil.findControl(control)
        if not pointer:
            raise RuntimeError("Maya sculpt viewport could not be created")
        self.view_widget = wrapInstance(int(pointer), QtWidgets.QWidget)
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.viewport.addWidget(self.view_widget)
        self.view_widget.show()
        cmds.modelEditor(self.panel, edit=True, grid=False, displayAppearance="smoothShaded", displayLights="default")
        self.bind_view()
        om.MGlobal.setActiveSelectionList(self.previous_selection)
        self.scene_callbacks = [om.MSceneMessage.addCallback(event, lambda *args: self.close())
                                for event in (om.MSceneMessage.kBeforeNew, om.MSceneMessage.kBeforeOpen)]
        self.scene_callbacks.extend(om.MEventMessage.addEventCallback(event, self.pause_auto_apply)
                                    for event in ("Undo", "Redo"))

    def eventFilter(self, watched, event):
        if self.auto_apply.isChecked() and self.panel:
            if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.TabletPress):
                self._apply_timer.stop()
                view = self.view_widget
                inside = isinstance(watched, QtWidgets.QWidget) and (watched is view or view.isAncestorOf(watched))
                if inside and self.editing and event.button() == QtCore.Qt.LeftButton and not event.modifiers() & QtCore.Qt.AltModifier:
                    self._stroke = True
            elif event.type() in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.TabletRelease):
                if self._stroke and event.button() == QtCore.Qt.LeftButton:
                    self._stroke = False
                    self._pending_apply = True
                if self._pending_apply and not event.buttons():
                    self._apply_timer.start()
        if watched is getattr(self, "view_widget", None):
            if event.type() == QtCore.QEvent.Enter and self.brush_command:
                self.run(lambda: self.tool(self.brush_command))
            elif event.type() == QtCore.QEvent.Leave:
                self.leave_brush()
        return super().eventFilter(watched, event)

    def auto_apply_changed(self, enabled):
        self.cancel_auto_apply()
        self.status.setText("ストローク後に反映 · 操作中は更新しません" if enabled else "手動反映 · ドラフトは保持されています")

    def cancel_auto_apply(self):
        self._apply_timer.stop()
        self._pending_apply = self._stroke = False

    def pause_auto_apply(self, *args):
        if self.auto_apply.isChecked():
            self.auto_apply.setChecked(False)
            self.status.setText("Undo / Redoのため自動反映を停止 · 必要なら手動で適用してください")

    def auto_commit(self):
        if not self._pending_apply or not self.auto_apply.isChecked() or not self.panel:
            return
        if self._stroke or QtWidgets.QApplication.mouseButtons():
            return  # A later release restarts the single-shot timer; no polling.
        self._pending_apply = False
        try:
            surface = self.capture()
            if surface != self._last_applied:
                self.commit(surface)
            else:
                self.restore_boundary()
        except Exception as exc:
            self.auto_apply.setChecked(False)
            self.status.setText("自動反映を停止: " + str(exc))
            self.status.setToolTip(str(exc))

    def reset_surface(self):
        self.cancel_auto_apply()
        self.auto_apply.setChecked(False)
        self.apply_surface({})
        self._last_applied = None
        self.status.setText("保存先の立体編集を解除 · ドラフトは保持されています")

    def choose_brush(self, command):
        self.brush_command = command
        # Maya contexts are global: activate only while the pointer is in our view.
        self.leave_brush()

    @viewport_undo_disabled()
    def leave_brush(self):
        from maya import cmds
        from maya.api import OpenMaya as om
        if self.editing:
            self.editing = False
            om.MGlobal.setActiveSelectionList(self.previous_selection)
            if self.previous_tool and cmds.contextInfo(self.previous_tool, exists=True):
                cmds.setToolTo(self.previous_tool)

    @viewport_undo_disabled()
    def bind_view(self):
        from maya import cmds
        if not self.panel:
            return
        self.cancel_auto_apply()
        self._last_applied = self.capture()
        self.restore_filters()
        name = self.function().fullPathName()
        visible = [name]
        if self.direction_marker and cmds.objExists(self.direction_marker):
            visible.append(self.direction_marker)
        cmds.select(visible, replace=True)
        if self.view_filter and cmds.objExists(self.view_filter):
            cmds.delete(self.view_filter)
        self.view_filter = cmds.itemFilter(byName="BifrostScales_Sculpt*")
        cmds.modelEditor(self.panel, edit=True, filter=self.view_filter)
        # The list filter alone does not isolate VP2 rendering. Keep an explicit
        # per-editor object set; subsequent scene selections must not change it.
        cmds.modelEditor(self.panel, edit=True, viewSelected=True)
        cmds.modelEditor(self.panel, edit=True, setSelected=True)
        cmds.select(name, replace=True)
        # Native name filters avoid a per-object Python callback during viewport redraw.
        for panel in cmds.getPanel(type="modelPanel"):
            if panel == self.panel:
                continue
            previous = cmds.modelEditor(panel, query=True, filter=True)
            excluded = cmds.itemFilter(byName="BifrostScales_Sculpt*", negate=True)
            active = cmds.itemFilter(intersect=(previous, excluded)) if previous else excluded
            cmds.modelEditor(panel, edit=True, filter=active)
            self.filters.append((panel, previous, active, excluded))
        self.frame()

    @viewport_undo_disabled()
    def frame(self):
        from maya import cmds
        from maya.api import OpenMaya as om
        if self.panel:
            selection = om.MGlobal.getActiveSelectionList()
            try:
                visible = [self.function().fullPathName()]
                if self.direction_marker and cmds.objExists(self.direction_marker):
                    visible.append(self.direction_marker)
                cmds.select(visible, replace=True)
                cmds.viewFit(self.camera, allObjects=False)
            finally:
                om.MGlobal.setActiveSelectionList(selection)

    def restore_filters(self):
        from maya import cmds
        for panel, previous, active, excluded in self.filters:
            if cmds.modelPanel(panel, exists=True) and cmds.modelEditor(panel, query=True, filter=True) == active:
                cmds.modelEditor(panel, edit=True, filter=previous or "")
            for node in set((active, excluded)):
                if cmds.objExists(node):
                    cmds.delete(node)
        self.filters = []

    @viewport_undo_disabled()
    def close_view(self):
        from maya import cmds
        from maya.api import OpenMaya as om
        self.cancel_auto_apply()
        QtWidgets.QApplication.instance().removeEventFilter(self)
        for callback in self.scene_callbacks:
            om.MMessage.removeCallback(callback)
        self.scene_callbacks = []
        self.leave_brush()
        self.restore_filters()
        if self.panel and cmds.modelEditor(self.panel, exists=True):
            cmds.deleteUI(self.panel)
        if self.host and cmds.window(self.host, exists=True):
            cmds.deleteUI(self.host, window=True)
        if self.view_filter and cmds.objExists(self.view_filter):
            cmds.delete(self.view_filter)
        if self.direction_marker and cmds.objExists(self.direction_marker):
            cmds.delete(self.direction_marker)
        if self.camera and cmds.objExists(self.camera):
            cmds.delete(self.camera)
        self.panel = self.host = self.camera = self.direction_marker = self.view_filter = None

    def closeEvent(self, event):
        self.close_view()
        super().closeEvent(event)

    def done(self, result):
        self.close_view()
        super().done(result)

    def run(self, action):
        try:
            action()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Interior Sculpt", str(exc))

    def function(self):
        from maya.api import OpenMaya as om
        if not self.mesh or not self.mesh.isValid() or not self.mesh.isAlive():
            raise ValueError("編集メッシュを作成または再開してください。")
        return om.MFnMesh(self.mesh.object())

    def new_patch(self):
        from maya import cmds
        self.cancel_auto_apply()
        value, accepted = QtWidgets.QInputDialog.getItem(
            self, "新規パッチ", "空のパッチの分割数。現在のドラフトは削除しません。",
            ["32", "64", "128"], 0, False)
        if not accepted:
            return
        self.leave_brush()
        old = self.mesh, self.surface, self.disk
        old_name = self.function().fullPathName() if self.mesh else None
        self.mesh = None
        self.surface = normalize_surface({"schema": "vector-surface/3", "resolution": int(value)})
        self.disk = True
        self.resolution.setCurrentIndex(self.resolution.findData(int(value)))
        try:
            self.create_or_update()
        except Exception:
            self.mesh, self.surface, self.disk = old
            raise
        if old_name and cmds.attributeQuery("bifrostSculptOwner", node=old_name, exists=True):
            cmds.setAttr(old_name+".bifrostSculptOwner", "", type="string")
        self.bind_view()
        self.status.setText("新規ドラフト · まだ適用されていません")

    def points(self):
        from maya.api import OpenMaya as om
        fn = self.function()
        counts, vertices = fn.getVertices()
        n = self.surface["resolution"]
        expected = [3]*(2*n*n) if self.disk else [4]*(n*n)
        if list(counts) != expected or list(vertices) != grid_faces(n, self.disk):
            raise ValueError("編集メッシュのトポロジーが変更されています。適用できません。")
        return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kObject)]

    def capture(self):
        return capture_surface(self.surface, self.points(), self.disk)

    def restore_boundary(self):
        from maya import cmds
        if self.surface["schema"] != "vector-surface/3":
            return
        points = self.points()
        n = self.surface["resolution"]
        name = self.function().fullPathName()
        cmds.undoInfo(openChunk=True, chunkName="Restore Sculpt Boundary")
        try:
            for j in range(n+1):
                for i in range(n+1):
                    if min(i,j,n-i,n-j) != 0:
                        continue
                    index = j*(n+1)+i
                    target = editor_rest_point(i/n, j/n, self.disk)
                    if max(abs(a-b) for a,b in zip(points[index],target)) > 1e-7:
                        cmds.xform(name+".vtx[{}]".format(index), objectSpace=True, translation=target)
        finally:
            cmds.undoInfo(closeChunk=True)

    def create_or_update(self):
        from maya import cmds
        from maya.api import OpenMaya as om
        if self.mesh:
            cmds.select(self.function().fullPathName(), replace=True)
            return
        surface = normalize_surface(dict(self.surface, resolution=self.resolution.currentData()))
        points = [om.MPoint(*p) for p in editor_points(surface, self.disk)]
        if self.mesh:
            self.function().setPoints(points, om.MSpace.kObject)
        else:
            n = surface["resolution"]
            fn = om.MFnMesh()
            result = fn.create(points, [3]*(2*n*n), grid_faces(n, True))
            # MFnMesh.create without a parent returns the transform.
            selection = om.MSelectionList()
            selection.add(cmds.rename(om.MFnDagNode(result).fullPathName(), "BifrostScales_SculptPatch#"))
            path = selection.getDagPath(0)
            path.extendToShape()
            self.mesh = om.MObjectHandle(path.node())
            name = self.function().fullPathName()
            cmds.sets(name, edit=True, forceElement="initialShadingGroup")
            cmds.addAttr(name, longName="bifrostSculptSurface", dataType="string")
            cmds.addAttr(name, longName="bifrostSculptLayout", dataType="string")
            cmds.setAttr(name+".bifrostSculptLayout", "disk-triangles/1", type="string")
        self.surface = surface
        self.resolution.setEnabled(False)
        cmds.setAttr(self.function().fullPathName()+".bifrostSculptSurface", json.dumps(surface), type="string")
        if self.owner_key:
            cmds.addAttr(self.function().fullPathName(), longName="bifrostSculptOwner", dataType="string")
            cmds.setAttr(self.function().fullPathName()+".bifrostSculptOwner", self.owner_key, type="string")
        cmds.select(self.function().fullPathName(), replace=True)

    def resume(self):
        from maya import cmds
        from maya.api import OpenMaya as om
        self.cancel_auto_apply()
        selection = om.MGlobal.getActiveSelectionList()
        if selection.length() != 1:
            raise ValueError("再開する編集パッチを1つ選択してください。")
        path = selection.getDagPath(0)
        if path.node().hasFn(om.MFn.kTransform):
            path.extendToShape()
        name = path.fullPathName()
        if not cmds.attributeQuery("bifrostSculptSurface", node=name, exists=True):
            raise ValueError("選択したメッシュは編集パッチではありません。")
        surface = normalize_surface(json.loads(cmds.getAttr(name+".bifrostSculptSurface")))
        layout = cmds.getAttr(name+".bifrostSculptLayout") if cmds.attributeQuery("bifrostSculptLayout", node=name, exists=True) else "square-quads/1"
        if layout not in ("disk-triangles/1", "square-quads/1"):
            raise ValueError("Unsupported sculpt editing layout")
        previous = self.mesh, self.surface, self.disk
        self.mesh, self.surface = om.MObjectHandle(path.node()), surface
        self.disk = layout == "disk-triangles/1"
        try:
            self.points()
        except Exception:
            self.mesh, self.surface, self.disk = previous
            raise
        if self.resolution.findData(surface["resolution"]) < 0:
            self.resolution.addItem(str(surface["resolution"]), surface["resolution"])
        self.resolution.setCurrentIndex(self.resolution.findData(surface["resolution"]))
        self.resolution.setEnabled(False)
        self.bind_view()

    @viewport_undo_disabled()
    def tool(self, command):
        from maya import cmds, mel
        from maya.api import OpenMaya as om
        if self.panel and not self.editing:
            self.previous_selection = om.MGlobal.getActiveSelectionList()
            self.previous_tool = cmds.currentCtx()
            self.editing = True
        self.brush_command = command
        cmds.select(self.function().fullPathName(), replace=True)
        if self.panel:
            cmds.setFocus(self.panel)
        mel.eval(command+";")

    def commit(self, surface=None):
        self.cancel_auto_apply()
        surface = self.capture() if surface is None else surface
        self.apply_surface(surface)
        self.restore_boundary()
        self._last_applied = surface
        self.status.setText("適用しました · ドラフトは保持されています")
