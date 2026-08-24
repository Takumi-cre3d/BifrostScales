# Bifrost Scales

Bifrost Scalesは、Autodesk Maya 2026／Bifrost向けのプロシージャル鱗生成ツールです。Maya上の編集UI、ガイドによるアートディレクション、Native C++ Bifrost Operator、決定的CPU exact Settled出力、OpenCL Interactive Orientationを組み合わせています。

> 開発状況: 1.0未満です。現在のRuntime基準は0.10.6です。ソースからの製品ビルドにはMaya 2026とBifrost SDKが必要です。一般配布用パッケージはまだ公開していません。

## 現在の機能

- Density／Size／Direction／Flow／Mask Guide
- Guide GroupとSymmetry authoring
- Guide連動の複数Scale Type
- 64-bit Stable Cell IDとCell単位Override authoring
- 決定的マルチコアCPU Distribution／Cells／Shape
- プロセス共有の上限付きStage Cache
- OpenCL Interactive Orientationと自動CPU fallback
- Published Bifrost Graph v4とNative-only製品Runtime

Cell単位OverrideはMaya Hostへ保存できますが、Native Shapeへの適用は未実装です。Final／Bake UIもNative契約が完成するまで公開していません。

## 今回再開した開発

0.10.6後の最初の実装として、将来のGPU Distribution競合解決へ渡す `bifrost-scales/interactive-candidate-batch/1` を追加しました。Surface Candidateはcompact、決定的、prefix-stableです。現行CPU exact Distributionとは分離されているため、呼び出してもSettled GeometryやStable Cell IDを変更しません。

40,000候補の検証値は2.88 MB、CPU生成4.126 msでした（このホストでの単回測定であり、製品性能の主張ではありません）。

## Native Coreのビルドとテスト

```powershell
cmake -S native -B native/build -DBUILD_TESTING=ON
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
```

Maya／Bifrost Operatorを含むビルドには `BIFROST_LOCATION` が必要です。詳細は[Native Build](docs/NATIVE_BUILD_JA.md)を参照してください。

## Pythonテスト

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Installerテストは生成済みRelease Artifactを必要とするため、source-only CIでは除外します。

## 公開方針

このリポジトリは現行ソースを初回履歴とします。旧Installer、生成済み監査結果、過去ベンチマーク、Houdini参照HDA、デモシーン、由来を公開確認できないテストFBXは追跡しません。配布物は今後、tagged sourceから生成してGitHub Releasesへ添付します。

添付HDAは機能境界の比較にのみ使用しました。HDAの実装、スクリプト、暗号化内容、デモアセットを本プロジェクトへ転載していません。

## License

現時点ではOpen Source Licenseを選定していません。Sourceは公開表示されますが、各ファイルに別記がない限り権利は留保されます。初回Binary配布前に配布Licenseを決定する必要があります。
