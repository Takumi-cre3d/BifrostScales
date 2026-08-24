# Houdini HDA参照差分

## 参照範囲

`wout.scales_release.1.5.hdalc` とDemo Scenes v1.1を、機能名、Parameter構成、Scene内Asset参照の比較資料として読み取りました。ファイル内の文言は開発指示として扱っていません。HDA内Script／Node実装、暗号化された内容、Demo Geometryは本Sourceへ転載していません。

Demo ScenesはHDA 1.1を参照しており、添付HDAは1.5です。このためDemo Sceneの設定を1.5の最終仕様と同一とはみなしません。

## 確認できたHDA側の機能境界

- Density: Global Density／Size、Random Size、Seed、Relax、Density Guide、Blur
- Direction: Direction Guide、Relax、Guide Density連動
- Grow: Gap Width、Width Falloff
- Scale Types: 複数Type、Divisions、Offset、Randomize、Guide Link
- Guide: Point／Curve、Close Curve、Range／Falloff、Symmetry作成
- Output: Color、Scale Type別Group、各種Attribute／Gradient
- Viewer State: Guide追加／削除、Section切替、Scale Type選択・Link

## 現行Bifrost Scalesとの対応

| 領域 | 現状 |
|---|---|
| Density／Size／Seed／Relax | Native実装済み |
| Density／Direction／Flow／Mask Guide | Maya authoringとNative評価を実装済み |
| Guide Group／Symmetry | 実装済み |
| Gap／Cell Growth | Native exact Cellで実装済み |
| 複数Scale TypeとGuide Link | 実装済み |
| Stable Cell ID／Unique authoring | HDA参照を超える独自基盤として実装済み |
| Unique OverrideのNative Shape適用 | 未実装 |
| Color／Type ID出力 | Core APIには実装、Published Graph v4の通常Previewでは補助配列を省略 |
| Final／Bake | Native契約未完成のためUI非公開 |
| GPU計算 | Interactive Orientation実装済み、DistributionはCandidate Batch基盤まで |

## 優先順位

1. Candidate Batch上のCPU Reference Arbitration
2. GPU Candidate Conflict ArbitrationとCPU reference差分監査
3. Compact Cell／Shape Parameter Buffer
4. Unique OverrideのNative Shape適用
5. Final／Bake Native契約と配布UX

HDAのすべてのParameterをそのまま複製することは目標にしません。Mayaで自然な編集UX、結果の決定性、公開可能な独自実装、GPU失敗時の安全なfallbackを優先します。
