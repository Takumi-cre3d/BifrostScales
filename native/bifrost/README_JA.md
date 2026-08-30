# Bifrost Operator Adapter — 0.10.7

Static Graph v4からSource Mesh配列とPayload 10を受け取り、Native Core 0.10.7を評価してBifrost Mesh用配列を返します。

```text
Contract        bifrost-scales/operator-contract/18
Behavior        bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1
Profile output  bifrost-scales/native-profile/9
```

Profile 9はStage別時間、Cache Hit、Worker数に加え、GPU request／availability／device、upload／kernel／readback時間、fallback reason、境界Density適応、プロセス共有Cache状態を返します。

GPUはInteractive Distribution conflictと対象となるOrientationに使用します。Bifrost Mesh encode、construct_mesh、DistributionはInteractiveでOpenCL、Settledで決定的CPU三角形Field補間、Finalで候補ごとのCPU exactです。0.10.5以前のDLLは再利用せず、0.10.7 SourceからClean Buildしてください。
