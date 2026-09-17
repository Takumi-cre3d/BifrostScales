"""UI-only translations; never translate scene names or serialized enum values."""
from .qt_compat import QtCore, QtGui, QtWidgets

# English keys also accept the existing Japanese captions as source text.
CAPTIONS = {
    "Sculpt Scales": "鱗をスカルプト",
    "Placement & Shape": "配置・形状", "Guide Editor": "ガイド編集",
    "Display & Updates": "表示・更新",
    "New System": "新規システム", "Target Actions": "対象メッシュの操作",
    "Create Mesh": "実メッシュを作成", "Mesh created": "メッシュを作成しました",
    "Create an independent Maya mesh from the current preview. The source system is preserved.": "現在のプレビューから独立したMayaメッシュを作成します。元のシステムは残ります。",
    "Wait for the preview to finish before creating a mesh.": "プレビューの更新完了後にメッシュを作成してください。",
    "Visible": "表示", "Lock": "ロック",
    "Show or hide the guide; scale generation is unchanged.": "ガイドの表示・非表示。鱗の生成には影響しません。",
    "Prevent deleting, renaming or reparenting the guide. This is not a transform lock.": "ガイドの削除・リネーム・親変更を防ぎます。移動や変形を固定する機能ではありません。",
    "Global": "全体設定", "Guides": "ガイド", "Scale Types": "鱗タイプ",
    "Preview": "プレビュー", "Status": "状態", "Idle": "待機中",
    "System / Target": "システム / 対象", "System": "システム",
    "Refresh": "再検索", "Delete System": "System削除",
    "Create from Selected Mesh": "選択メッシュから新規作成（Bifrost Previewまで）",
    "Use Selected Mesh": "選択メッシュへ変更", "Reload Target Shape": "Target形状を再読込",
    "Target: Not Set": "Target: 未設定", "Maintenance": "メンテナンス",
    "Diagnostics": "環境診断", "Show Advanced Parameters": "詳細パラメータを表示",
    "1. Distribution": "1. 配置", "2. Orientation / Flow": "2. 向き・流れ",
    "3. Boundary / Surface": "3. 鱗の境界・表面", "4. Base Shape": "4. 鱗の基本形状",
    "Scale Count": "鱗の数", "Seed": "ランダムシード", "Spacing": "配置間隔",
    "Distribution Relaxations": "配置の均し回数", "Distribution Relax Strength": "配置の均し強度",
    "Reset Distribution": "配置を既定値へ戻す", "Orientation": "全体の向き",
    "Random Rotation": "向きのランダム幅", "Orientation Relaxations": "向きの均し回数",
    "Orientation Relax Strength": "向きの均し強度", "Reset Orientation": "向きを既定値へ戻す",
    "Interactive Display": "操作中の表示", "Auto: Cards While Editing / Cells When Idle": "Auto: 操作中Card / 停止後Cell",
    "Cards only": "簡易表示のみ", "Cells while dragging": "操作中も詳細表示",
    "Gap": "鱗の隙間", "Collision Margin": "衝突余白", "Open Boundary Extent": "開いた境界の範囲",
    "Flow Elongation": "流れ方向への伸び", "Boundary Subdivisions": "境界の分割数",
    "Interior Subdivisions": "内側の分割数", "Surface Follow Rings": "表面追従リング",
    "Reproject Boundary onto Target": "Cell境界をTargetへ再投影", "Reset Boundary": "境界を既定値へ戻す",
    "Shape Strength": "形状の強さ", "Surface Lift": "表面からの浮き", "Interior Thickness": "内部の厚み",
    "Curvature": "反り", "Sculpt Interior…": "内側を立体編集…", "Inset": "縁の絞り",
    "Squash": "潰れ", "Expand": "広がり", "Tip Roundness": "先端の丸み",
    "Tip Shift": "先端のずれ", "Forward Shift": "前後のずれ",
    "Random Shape Strength": "形状の強さのばらつき", "Reset Shape": "形状を既定値へ戻す",
    "Shape Strength Multiplier": "形状の強さ倍率", "Sculpt This Type…": "このTypeの内側を立体編集…",
    "Thickness Adjustment": "内部の厚み補正", "Preview Backend": "生成方式",
    "Check Native Environment": "Native環境を確認", "Rebuild Native Graph": "Native Graphを再構築",
    "Delete Native Graph": "Native Graphを削除", "Native Status": "生成エンジンの状態",
    "Auto Preview": "自動プレビュー", "Show Preview": "Previewを表示",
    "Interactive Limit": "Interactive上限", "Adjust Limit Automatically": "上限を自動調整",
    "Reason": "選択理由", "Interactive Interval": "Interactive間隔", "Refine Delay": "停止後Refine",
    "Pause": "一時停止", "Clear Fault": "Fault解除", "Performance": "処理時間",
    "Name": "名前", "Active": "有効", "Enabled": "有効化", "Group": "グループ",
    "Add": "追加", "Delete": "削除", "Remove": "取り除く", "Duplicate": "複製",
    "Up": "上へ", "Down": "下へ", "Rebuild": "再構築", "None": "なし",
    "New Guide Group": "新規ガイドグループ", "Create Guide Point": "ガイド点を作成",
    "Draw Guide Curve": "ガイドカーブを描画", "Selected Guide": "選択ガイド",
    "Selected Guide Group": "選択グループ", "Enable for all members": "全メンバーを有効化",
    "Search Guides and Groups": "ガイドとグループを検索", "Guide Link": "ガイド連携",
    "Scale Type Link": "鱗タイプ連携", "Show Linked": "連携対象を表示",
    "Jump to Link": "連携対象へ移動", "Assign Here": "ここへ割り当て", "Unassign": "割り当て解除",
    "Closed Curve": "閉じたカーブ", "Effects": "効果", "Density": "密度",
    "Density Effect": "密度効果", "Density Multiplier": "密度倍率", "Direction": "方向",
    "Direction Strength": "方向の強さ", "Direction Angle": "方向角度",
    "Direction Angle Offset": "方向角度の補正", "Size": "サイズ",
    "Size Effect": "形状の強さの効果", "Size Multiplier": "形状の強さの倍率",
    "Range": "範囲", "Falloff": "減衰", "Mask": "マスク", "Center Alignment": "中心整列",
    "Cell Anisotropy": "セルの方向性", "Symmetry": "対称", "Symmetry Axis": "対称軸",
    "Symmetry Space": "対称座標", "World": "ワールド", "Target Local": "対象のローカル",
    "Custom Vertex Color": "個別の頂点色", "Color": "色", "Random Offset": "ランダムオフセット",
    "Tip Offset": "先端オフセット", "Info": "情報", "Ungrouped": "グループなし",
    "Subdivisions": "分割数", "Patch Actions": "パッチ操作", "Apply": "適用",
    "Apply After Stroke": "ストローク後に適用", "New Patch (Choose Subdivisions)…": "新規パッチ（分割数を指定）…",
    "Resume Selected Patch": "選択中の編集パッチを再開", "Frame Patch": "パッチ全体を表示",
    "Reset Sculpt (Types Inherit Global)": "保存先の立体編集を解除（TypeはGlobalに戻る）",
    "Manual Apply · Draft Persists When Closed": "手動反映 · ドラフトは閉じても保持されます",
    "Interior Sculpt": "編集用パッチ", "Sculpt": "盛る", "Grab — 3 Axes": "つかむ — 3方向", "Smooth": "滑らかに",
    "Apply after editing stops. Disable for heavy systems.": "操作が止まってから変更を反映します。重いSystemではOFFにしてください。",
    "The yellow arrow points forward (+V). Sculpt the interior, apply, and inspect the main view. The boundary and gap stay fixed.": "黄色の矢印が前方（+V）です。内側をスカルプト → 適用して元のビューで確認。外周・Gapは保持します。",
    "Shape strength controls curvature, thickness and sculpt displacement, not the boundary size.": "形状の強さ。外周サイズではなく反り・厚み・スカルプト変位の基準。",
    "Interior thickness; the boundary stays fixed. Type thickness adjustments are added.": "内部の厚み。外周は固定。Typeの厚み補正を加算します。",
    "Added to global interior thickness; the boundary stays fixed.": "Globalの内部厚みに加算する補正値。外周は固定します。",
    "Show advanced controls. This preference is not saved in the scene.": "高度な調整項目だけを表示します。この表示状態はSceneへ保存しません。",
    "Guide stroke direction controls scale orientation. Reverse the stroke to turn scales by 180 degrees.": "ガイドの描画方向で鱗の前後を指定します。逆向きに描くと180°反転します。",
    "Edit interior shape and thickness while preserving the boundary and gap. Thickness is a percentage of shape strength.\nVertex colors are managed per Scale Type.": "外周・Gapを保持し、内部の形状と厚みを調整します。厚みは形状の強さを基準にした%表示です。\n色はScale TypesごとのVertex Colorで管理します。",
    "Creation automatically builds the system, mesh connection, native graph and initial preview.": "新規作成時にSystem、worldMesh接続、Native Graph、初回Previewを自動作成します。",
    "Linked types use the strongest local Guide/Group link without random competition between links.": "Guide／Group LinkがあるTypeは、その位置で最も強いLinkを確定採用します。複数Typeを別Guideへ割り当てても相互に抽選競合しません。",
    "0: Full effect throughout the range. 1: Fade from the center to the range boundary.": "0: Range全域で完全効果。1: 中心からRange外端まで全域で減衰。",
    "0: Isotropic cells. 1: Up to 2.25x elongation within guide influence.": "0は従来の等方Cell、1はGuide効果内で最大2.25倍の方向性を与えます。",
    "Cell center candidates along a Direction Curve. 0: None. 1: One candidate per distribution interval.": "Direction Curve上へ配置するCell中心候補の量です。0で中心列なし、1で分布間隔ごとに候補を作成します。",
    "Exclude mesh output for completed cells within range. Falloff controls the fade width. Mask guides are magenta in the viewport.": "Range内の完成Cellからメッシュ出力だけを除外します。FalloffはRangeに対する減衰幅です。Mask GuideはViewportでマゼンタ表示されます。",
    "World uses the world origin; Target Local uses the target transform origin for symmetry.": "Worldはワールド原点、Target LocalはTarget Transform原点を対称面の中心に使います。",
    "Guide influence on cell boundary orientation, independent of Direction Strength and Center Alignment.": "このGuideがCell境界を方向付ける強さです。Direction StrengthやCenter Alignmentとは独立しています。",
    "Reset only this section. Restore with one Undo.": "このSectionだけを既定値へ戻します。1回のUndoで復元できます。",
    "Apply group symmetry axis and space to member guides non-destructively while enabled.": "オンの間だけGroupのAxis / Spaceを所属Guideへ非破壊で適用します。",
    "Mirror guides at evaluation time without duplicating scene objects.": "実体Guideを複製せず、評価時だけ鏡像Guideを追加します。",
    "Multiply member Direction Strength by 0–1. At 1, individual strengths remain unchanged.": "所属GuideのDirection Strengthに0〜1の範囲で乗算します。1が個別値をそのまま使う最大値です。",
    "Orient scales toward a point or along a curve. Does not affect center placement or boundary anisotropy.": "鱗のOrientationがPointまたはCurve方向へ沿う強さです。Cell中心配置とCell境界の異方性には影響しません。",
    "Distribution smoothing strength. Default: 0.45 / Affects: Distribution": "配置を均す強さ。既定値: 0.45 / 影響: 配置",
    "Orientation smoothing strength. Default: 0.35 / Affects: Orientation": "向きを均す強さ。既定値: 0.35 / 影響: 向き",
    "Interior surface-follow rings. Default: 2 / Affects: Boundary": "Target表面へ追従させる内側リング数。既定値: 2 / 影響: 境界",
    " / Disabled: Relaxations is zero": " / 均し回数が0のため無効",
    " / Disabled: Surface reprojection is off": " / 表面への再投影がOffのため無効",
}
ALIASES = {"Maintenance / メンテナンス": "Maintenance", "Interior Sculpt — 編集用パッチ": "Interior Sculpt",
           "盛る / Sculpt": "Sculpt", "つかむ / Grab — 3方向": "Grab — 3 Axes", "滑らかに / Smooth": "Smooth"}
_REVERSE = {value: key for key, value in CAPTIONS.items()}


def language():
    return str(QtCore.QSettings("BifrostScales", "UI").value("language", "ja"))


def set_language(value):
    if value not in ("en", "ja"):
        raise ValueError("Unsupported UI language")
    QtCore.QSettings("BifrostScales", "UI").setValue("language", value)


def translate(text, locale=None):
    if " / " in text:
        # Dependency hints append a translated disabled reason to a tooltip.
        for suffix in (" / 均し回数が0のため無効", " / 表面への再投影がOffのため無効"):
            for candidate in (suffix, _REVERSE[suffix]):
                if text != candidate and text.endswith(candidate):
                    return translate(text[:-len(candidate)], locale) + translate(candidate, locale)
    key = ALIASES.get(text, text)
    key = _REVERSE.get(key, key)
    return CAPTIONS.get(key, text) if (locale or language()) == "ja" else key


def translate_window(root, locale=None):
    """Translate captions only, never editable fields, combo data or tree items."""
    locale = locale or language()
    for widget in [root, *root.findChildren(QtWidgets.QWidget)]:
        for getter, setter in (("toolTip", "setToolTip"), ("accessibleName", "setAccessibleName"),
                               ("windowTitle", "setWindowTitle")):
            source = getattr(widget, getter)()
            getattr(widget, setter)(translate(source, locale))
        if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
            widget.setText(translate(widget.text(), locale))
        elif isinstance(widget, QtWidgets.QGroupBox):
            widget.setTitle(translate(widget.title(), locale))
        elif isinstance(widget, QtWidgets.QTabWidget):
            for index in range(widget.count()):
                widget.setTabText(index, translate(widget.tabText(index), locale))
        if isinstance(widget, QtWidgets.QLineEdit):
            widget.setPlaceholderText(translate(widget.placeholderText(), locale))
    action_class = getattr(QtGui, "QAction", None) or QtWidgets.QAction
    for action in root.findChildren(action_class):
        action.setText(translate(action.text(), locale))
