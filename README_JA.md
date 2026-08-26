# Bifrost Scales

Bifrost Scalesは、Autodesk Maya 2026／Bifrost向けのプロシージャル鱗生成ツールです。Maya上の編集UI、ガイドによるアートディレクション、Native C++ Bifrost Operator、決定的CPU exact Settled出力、Interactive Orientation用OpenCLアクセラレーションを組み合わせています。

[English](README.md)

## 必要環境と開発状況

- Autodesk Maya 2026
- Autodesk Bifrost for Maya 2026
- Native source build時はMaya C++ toolchainとBifrost SDK
- Runtime基準: 0.10.6
- 開発状況: pre-1.0。一般配布用Packageは未公開

## 機能

- Rangeを外端、0〜1のFalloffを減衰幅としてメッシュ表面接続距離で評価するDensity／Size／Direction／Flow／Mask Guide
- Directionの向き、Direction Curveの中心整列、異方性Cell分割を独立調整（`Direction Strength`、Guide別`Center Alignment`／`Cell Anisotropy`、全体の`Cell Direction Anisotropy`）
- Maskは完成Cellの配置・形状を保持し、Stable Cell IDによる決定的な確率でメッシュ出力のみを制御
- Guide GroupとSymmetry authoring
- Guide連動の複数Scale Type
- 64-bit Stable Cell IDとメッシュ不要のPicker metadata
- 決定的マルチコアCPU Distribution／Cells／Shape
- 大きなCell半径やDensity差に対応するexact BVH Cell近傍探索
- Open Boundary候補をexact BVHで検索し、境界のない閉メッシュでは走査を省略するCell高速経路
- プロセス共有の上限付きStage Cache
- 編集間で再利用するTarget Mesh topology／境界／Surface Guide高速化データ
- PerformanceログにCell setup／neighbor／boundary候補検索／boundary ray／surface projectionの処理時間内訳を表示
- OpenCL Interactive Orientationと自動CPU fallback
- Published Bifrost Graph v4とNative-only製品Runtime

## Mayaでのワークフロー

1. Maya Python APIから `import bifrost_scales; bifrost_scales.show()` を実行してUIを開きます。
2. Polygon Meshを選択し、Bifrost Scales Systemを作成します。
3. Guideを追加・編集してDensity、Size、Direction、Flow、Maskを調整します。`Direction Strength`は鱗の向き、`Center Alignment`はCurve中心候補の割合、Guide別`Cell Anisotropy`は全体の`Cell Direction Anisotropy`に対する寄与を調整します。
4. 編集中はInteractive Preview、確定確認には決定的CPU exactのSettled Previewを使用します。
5. Maya Sceneを保存すると、System、Guide、Guide Group、Scale Type、Native Graph接続がSceneへ保存されます。

## 実行モデル

Settled出力は従来の決定的CPU exact経路を使用します。Interactive Distributionはcompact・決定的・prefix-stableなSurface Candidateを並列評価し、空間競合をOpenCLで裁定します。GPUを利用できない場合は同じ優先規則のCPU referenceへ自動fallbackします。CPUで生成するOpen Boundary／Guide Curve Anchor、表面接続Guide Field、Stable Cell ID、Maskのpost-Cell出力制御は維持されます。Direction異方性は中心点を追加・削除せず、隣接Cell間で対称な距離計量だけを変えます。全体効果の最大は上限付き2.25軸比で、Guideごとに効果を弱めるか無効化できます。

- `bifrost-scales/interactive-candidate-batch/1`: production Interactive Surface Candidate
- `bifrost-scales/interactive-conflict-reference/1`: 決定的CPU fallback
- `bifrost-scales/interactive-conflict-gpu/1`: CPUと同じ優先規則を保つ並列OpenCL裁定

GPU Conflictの自動Crossoverは既定8,192候補で、`BIFROST_SCALES_GPU_MIN_CANDIDATES`から上書きできます。

## 現在の制限

- Final／BakeはNative契約が完成するまでUIへ公開していません。
- 製品Native buildにはMaya 2026とBifrost SDKの開発環境が必要です。

## BuildとTest

```powershell
cmake -S native -B native/build -DBUILD_TESTING=ON
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Maya／Bifrost Operatorを含むbuildには `BIFROST_LOCATION` が必要です。詳細は[Native Build](docs/NATIVE_BUILD_JA.md)を参照してください。

## ドキュメント

- [Architecture](docs/ARCHITECTURE_JA.md)
- [Roadmap](docs/ROADMAP_JA.md)
- [Interactive Distribution Candidate Batch](docs/INTERACTIVE_DISTRIBUTION_CANDIDATE_BATCH_JA.md)
- [GPU Conflict Arbitration](docs/INTERACTIVE_DISTRIBUTION_GPU_CONFLICT_JA.md)
- [Maya Host Validation](docs/MAYA_HOST_TEST_JA.md)
- [Native Validation](docs/NATIVE_VALIDATION_JA.md)
