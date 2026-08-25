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

- メッシュ表面の接続距離でFalloffするDensity／Size／Direction／Flow／Mask Guide
- Guide GroupとSymmetry authoring
- Guide連動の複数Scale Type
- 64-bit Stable Cell IDとメッシュ不要のPicker metadata
- 決定的マルチコアCPU Distribution／Cells／Shape
- プロセス共有の上限付きStage Cache
- OpenCL Interactive Orientationと自動CPU fallback
- Published Bifrost Graph v4とNative-only製品Runtime

## Mayaでのワークフロー

1. Maya Python APIから `import bifrost_scales; bifrost_scales.show()` を実行してUIを開きます。
2. Polygon Meshを選択し、Bifrost Scales Systemを作成します。
3. Guideを追加・編集してDensity、Size、Direction、Flow、Maskを調整します。
4. 編集中はInteractive Preview、確定確認には決定的CPU exactのSettled Previewを使用します。
5. Maya Sceneを保存すると、System、Guide、Guide Group、Scale Type、Native Graph接続がSceneへ保存されます。

## 実行モデル

Settled出力は決定的CPU exact経路を使用します。Interactive Orientationは処理量が閾値を超えるとOpenCLを使用でき、利用できない場合はマルチコアCPUへ自動fallbackします。

Interactive Distribution基盤には、Host非依存の2つのContractがあります。

- `bifrost-scales/interactive-candidate-batch/1`: compact、決定的、prefix-stableなSurface Candidate
- `bifrost-scales/interactive-conflict-reference/1`: Density／Mask gateと空間競合裁定の決定的CPU reference
- `bifrost-scales/interactive-conflict-gpu/1`: CPUと同じ優先規則を保つ並列OpenCL裁定と自動CPU-reference fallback

これらのContractはMaya Runtimeへ未接続です。Settled Geometry、Stage Cache、Stable Cell IDは変更しません。GPU Conflictの自動Crossoverは既定8,192候補で、`BIFROST_SCALES_GPU_MIN_CANDIDATES`から上書きできます。

## 現在の制限

- Final／BakeはNative契約が完成するまでUIへ公開していません。
- Interactive Distribution GPU裁定はHost非依存であり、Maya Runtimeへ未接続です。
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
