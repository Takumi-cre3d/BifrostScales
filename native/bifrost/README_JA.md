# Bifrost Operator Adapter — 0.10.9

Static Graph v4からSource Mesh配列とPayload 10を受け取り、Native Core 0.10.9を評価してBifrost Mesh用配列を返します。

```text
Contract        bifrost-scales/operator-contract/20
Behavior        bifrost-scales/native-core/0.10.9-settled-proposal-index-1
Profile output  bifrost-scales/native-profile/11
```

Profile 10はStage別時間、Cache Hit、Worker数に加え、Guide Surface Fieldの時間とGuide別hit／miss数、Interactive Mesh Sampling Cache、GPU request／availability／device、upload／kernel／readback時間、fallback reason、境界Density適応、プロセス共有Cache状態を返します。

GPUはInteractive Distribution conflictと対象となるOrientationに使用します。Bifrost Mesh encode、construct_mesh、DistributionはInteractiveでOpenCL、Settledで決定的CPU三角形Field補間、Finalで候補ごとのCPU exactです。0.10.9より前のDLLは再利用せず、0.10.9 SourceからClean Buildしてください。
