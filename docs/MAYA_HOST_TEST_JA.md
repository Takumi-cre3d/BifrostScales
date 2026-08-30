# Maya 2026 Host Test — Bifrost Scales 0.10.8

## 1. Version／Native Pack

BifrostScales_0_10_8_POST_INSTALL_CHECK.pyをMaya Script EditorのPythonタブで実行します。Product、Pack、Minimum Packが0.10.8、ready=True、Payload／Behavior／Profile契約がすべてTrueなら合格です。

## 2. 新規作成

Polygon Meshを選び、「選択メッシュから新規作成（Bifrost Previewまで）」を押します。System、Native Graph、初回Settled Previewが作成されることを確認します。

## 3. Stage Cache

約17,000～30,000セル、Guide 10本以上の同じSettled入力を2回評価します。2回目が次の状態なら合格です。

~~~text
distribution=hit orientation=hit cell=hit
cache=process-shared-bounded/2
~~~

Shape生成時間は毎回発生します。初回評価後、TargetとGuide geometry／radiusが同一なら`guideSurface`のmissが0になります。InteractiveのTarget Meshが同一なら`meshSample=hit`、Settled／Finalでは`meshSample=n/a`が正常です。Guideを1本編集した場合は、そのGuide Fieldだけがmissとなり、他のGuide Fieldはhitを維持します。

## 4. Open Boundary BVH

1. 開放エッジを持つ同じSceneを複製し、同じTarget Count、Cell Sides、Guide、Densityを使います。
2. Cell GapまたはCell Collision Marginを小さく往復させ、Distribution／OrientationをHIT、CellsだけをMISSにします。
3. 各版でnative-profileのcells=を5回記録し、中央値を比較します。
4. `boundaryParts=query/rays`のqueryが旧版より短縮し、Cell数、境界、Mesh、Stable Cell IDが異方性0で一致すれば合格です。

ローカル30,000セル基準は111.633 msから89.971 ms（19.4%短縮）でした。ユーザー提供Sceneでは0.10.5のCellsが約2.7～4.1秒だったため、同じSceneの中央値を重視してください。

## 5. Direction異方性／GPU Orientation

Target CountとInteractive Budgetを4,096以上、Direction Relaxを0にし、Direction Guideをドラッグします。

変更項目ごとの期待cache境界は次のとおりです。

~~~text
Direction Strength: distribution=hit orientation=miss cell=hit cellBasis=guide-anisotropic
Center Alignment:    distribution=miss orientation=miss cell=miss
Guide Cell Anisotropy: distribution=hit orientation=miss cell=miss cellBasis=guide-anisotropic
Global Cell Direction Anisotropy: distribution=hit orientation=hit cell=miss
~~~

`Direction Strength`を固定し、Direction Curveの`Center Alignment`を0、0.35、1へ変えて、中心へ寄る候補数だけが増えることを確認します。次に`Center Alignment`を固定して`Direction Strength`を変え、鱗の向きだけが変わることを確認します。`Cell Direction Anisotropy=0`ではCell Cache basisが`distribution`になります。全体値を0.4、1.0へ上げ、Guide別`Cell Anisotropy`を0、0.5、1へ変えて、中心配置を保ったままCell境界の方向性だけが最大2.25軸比まで明確に変化することを確認します。

メッシュ表面接続距離を使うDirection Guideでは、Interactive Orientationも現在は理由付きCPU exact fallbackが正解です。停止後のSettledは常にgpu=Falseの決定的CPU Field Cache経路になります。Interactive Distribution側のGPU利用可否はnative-profileで別に確認します。

## 6. 開放エッジDensity

開放エッジ全体を覆うDensity GuideでMultiplierを1.0から0.25へ下げます。開放エッジ沿いのセル数も減り、大きなセルが同じ本数のまま押し込まれず、外側へはみ出さないことを確認します。

## 7. 保存・再読込

Sceneを保存して再読込し、System、Guide、Group、Scale Types、Native Graph接続、全体の`Cell Direction Anisotropy`、Guide別`Center Alignment`／`Cell Anisotropy`が保持されることを確認します。

## 8. Interactive Distribution基盤の回帰

`bifrost-scales/interactive-candidate-batch/1`、`bifrost-scales/interactive-conflict-reference/1`、`bifrost-scales/interactive-conflict-gpu/1`はMaya RuntimeのInteractive Distributionで使用されます。GPUが利用できない場合は同じ優先規則のCPU referenceへfallbackします。

同じMesh／Seed／SettingsでSettledを2回評価し、vertices、faces、Stable Cell IDと見た目が一致することを確認します。Interactive編集からSettledへ戻した結果が毎回一致すれば合格です。SettledとFinalはGuide Falloff境界で微小な差が許容されます。
