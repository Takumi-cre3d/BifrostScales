# Bifrost Scales Native Pack出力

0.7.1のBuild Scriptは、このコンテナ配下へBifrost SDKが決定したversioned install rootを作成します。

```text
BifrostScalesCore-0.7.1/
  BifrostScalesPackConfig.json
  lib/BifrostScalesOps.dll
  json/BifrostScales/operators/bifrost_scales_nodedef.json
  json/BifrostScales/graphs/BifrostScales_native_scales_v4_graph.json
  metadata/manifest.bifrost-scales.json
  tools/bifrost_scales_parity_dump.exe
```

Operator、依存Graph、非Bifrost metadataを同じjsonLibへ混在させないでください。

0.7.1はCell center Fanの幾何法線補正を含むFace winding挙動契約を更新するため、旧Packへ上書きせず`BifrostScalesCore-0.7.1`をClean Buildします。
