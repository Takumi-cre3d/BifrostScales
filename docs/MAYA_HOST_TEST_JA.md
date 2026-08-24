# Maya 2026 Host Test — Bifrost Scales 0.10.6

## 1. Version／Native Pack

BifrostScales_0_10_6_POST_INSTALL_CHECK.pyをMaya Script EditorのPythonタブで実行します。Product、Pack、Minimum Packが0.10.6、ready=True、Payload／Behavior／Profile契約がすべてTrueなら合格です。

## 2. 新規作成

Polygon Meshを選び、「選択メッシュから新規作成（Bifrost Previewまで）」を押します。System、Native Graph、初回Settled Previewが作成されることを確認します。

## 3. Stage Cache

約17,000～30,000セル、Guide 10本以上の同じSettled入力を2回評価します。2回目が次の状態なら合格です。

~~~text
distribution=hit orientation=hit cell=hit
cache=process-shared-bounded/2
~~~

Shape生成時間は毎回発生します。Guideを追加・編集して入力が変わった直後のMISSは正常です。

## 4. Cell Hot Path比較

1. 0.10.5と同じSceneを複製し、同じTarget Count、Cell Rays、Guide、Densityを使います。
2. Cell GapまたはCell Collision Marginを小さく往復させ、Distribution／OrientationをHIT、CellsだけをMISSにします。
3. 各版でnative-profileのcells=を5回記録し、中央値を比較します。
4. Cell数、境界、Mesh、Stable Cell IDが一致し、0.10.6中央値が悪化していなければ合格です。

ローカル30,000セル基準は111.633 msから89.971 ms（19.4%短縮）でした。ユーザー提供Sceneでは0.10.5のCellsが約2.7～4.1秒だったため、同じSceneの中央値を重視してください。

## 5. Direction編集／GPU Orientation

Target CountとInteractive Budgetを4,096以上、Direction Relaxを0にし、Direction Guideをドラッグします。

~~~text
distribution=hit orientation=miss cell=hit
backend=opencl-gpu+cpu-exact-settle gpu=True
~~~

停止後のSettledはgpu=FalseのCPU exactが正解です。GPUが使えない場合は理由付きCPU fallbackで生成が完了すれば安全性は合格です。

## 6. 開放エッジDensity

開放エッジ全体を覆うDensity GuideでMultiplierを1.0から0.25へ下げます。開放エッジ沿いのセル数も減り、大きなセルが同じ本数のまま押し込まれず、外側へはみ出さないことを確認します。

## 7. 保存・再読込

Sceneを保存して再読込し、System、Guide、Group、Scale Types、Unique Scale登録、Native Graph接続が保持されることを確認します。

## 8. Interactive Distribution基盤の回帰

`bifrost-scales/interactive-candidate-batch/1`、`bifrost-scales/interactive-conflict-reference/1`、`bifrost-scales/interactive-conflict-gpu/1` はMaya Runtimeへ未接続です。現在のSourceをbuildしてもUIや生成結果に新しい表示差は発生しません。

同じMesh／Seed／SettingsでSettledを2回評価し、vertices、faces、Stable Cell IDと見た目が一致することを確認します。Interactive編集からSettledへ戻した結果も従来のCPU exact結果と一致すれば合格です。
