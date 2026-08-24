# Bifrost Operator Adapter — 0.10.6

Static Graph v4からSource Mesh配列とPayload 10を受け取り、Native Core 0.10.6を評価してBifrost Mesh用配列を返します。

```text
Contract        bifrost-scales/operator-contract/18
Behavior        bifrost-scales/native-core/0.10.6-cell-hot-path-1
Profile output  bifrost-scales/native-profile/9
```

Profile 9はStage別時間、Cache Hit、Worker数に加え、GPU request／availability／device、upload／kernel／readback時間、fallback reason、境界Density適応、プロセス共有Cache状態を返します。

GPUはInteractive Orientationだけです。Bifrost Mesh encode、construct_mesh、Distribution、Settled／FinalはCPU exactです。0.10.5以前のDLLは再利用せず、0.10.6 SourceからClean Buildしてください。
