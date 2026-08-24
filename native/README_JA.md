# Bifrost Scales Native Core 0.10.6

## Post-0.10.6 Development

Interactive DistributionのGPU競合解決に先立ち、`interactive-candidate-batch/1` を追加しました。`preview_distribution.hpp` のAPIはcompactなSoA候補列を生成しますが、現行 `distribute()` には未接続です。Settled CPU exact結果とStable Cell IDは変更しません。

`bifrost_scales_candidate_batch_benchmark` で候補数、転送bytes、生成時間を計測できます。

Native CoreはDistribution、Orientation、Cell、ShapeをC++17で評価します。

0.10.6は全Cell共通のRay角度表、Sample Normal／Surface Componentの事前計算、Mask Guideなし高速経路、1 Sample = 1 Partition Siteの直接制約を追加します。計算順序と倍精度境界は維持し、0.10.5出力とbyte-exactです。

Interactive／Direction Relax 0のOrientationだけをOpenCL GPUへオフロードできます。OpenCLは動的ロードされ、失敗時はマルチコアCPUへ戻ります。Settled／Finalは常に倍精度CPU exactです。GPU Distributionは候補競合経路と一括で実装するまで無効です。

開放エッジ境界アンカーは局所Densityの平方根で重み付けしたArc Lengthへ配置します。neutral Densityは0.10.2互換です。

```text
Core version        0.10.6
Payload             bifrost-scales/native-payload/10
Operator            bifrost-scales/operator-contract/18
Behavior            bifrost-scales/native-core/0.10.6-cell-hot-path-1
Profile             bifrost-scales/native-profile/9
GPU Buffer          bifrost-scales/compact-orientation-buffer/1
```

ビルドにはC++17、Threads、Bifrost SDKが必要です。OpenCL SDKは不要です。
