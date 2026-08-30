# Bifrost Scales Native Core 0.10.8

## 0.10.8 Surface Guide／Sampling Cache

Interactive DistributionはTarget Meshの三角形面積累積表と法線をプロセス共有Cacheで再利用します。Surface Guide FieldはTarget topologyとGuide geometry／radiusで個別にkey化し、Guideを1本編集した場合はそのFieldだけを再構築します。全Fieldがhitする評価では全Guide共通の投影BVH構築も省略します。Profileは`guide_surface_ms`、Guide別hit／miss数、`interactive_surface_cache_hit`を出力します。決定的な配置結果、Finalの候補ごとのCPU exact評価、Stable Cell ID契約は維持します。

`bifrost_scales_candidate_batch_benchmark` で候補数、転送bytes、生成時間を計測できます。

Native CoreはDistribution、Orientation、Cell、ShapeをC++17で評価します。

Native Coreは全Cell共通のRay角度表、Sample Normal／Surface Componentの事前計算、Mask Guideなし高速経路、1 Sample = 1 Partition Siteの直接制約を使用します。Cell Direction Anisotropy=0では等方Cell境界計算を維持します。非0ではGuide別Cell Anisotropyと最大2.25軸比の上限付き異方性を使用し、Center Alignmentは中心候補数を独立制御します。

Interactive／Direction Relax 0のOrientationだけをOpenCL GPUへオフロードできます。OpenCLは動的ロードされ、失敗時はマルチコアCPUへ戻ります。Settledは倍精度CPUの決定的な三角形Field補間、Finalは候補ごとの倍精度CPU exactです。Interactive Distributionの候補競合はOpenCLへ接続済みで、利用不可時は同じ優先規則のCPU referenceへ戻ります。
複数反復するSettled Direction Relaxは、CPUで表面接続Guideを正確に評価した後、距離判定済みcompact CSR近傍と接線反復だけをOpenCLへ渡します。結果が不正またはGPUを利用できない場合はマルチコアCPUへ戻ります。
GPU転送前後のcompact変換は8k～15k Sampleでの一時スレッド起動を避ける直列処理で、Profileはpack／GPU call／unpackを分離して出力します。


開放エッジ境界アンカーは局所Densityの平方根で重み付けしたArc Lengthへ配置します。neutral Densityは0.10.2互換です。

```text
Core version        0.10.8
Payload             bifrost-scales/native-payload/10
Operator            bifrost-scales/operator-contract/19
Behavior            bifrost-scales/native-core/0.10.8-surface-guide-sampling-cache-1
Profile             bifrost-scales/native-profile/10
GPU Buffer          bifrost-scales/compact-orientation-buffer/2
```

ビルドにはC++17、Threads、Bifrost SDKが必要です。OpenCL SDKは不要です。
