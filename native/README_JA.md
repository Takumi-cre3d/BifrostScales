# Bifrost Scales Native Core 0.10.6

## Post-0.10.6 Development

Interactive Distributionは`interactive-candidate-batch/1`のcompactなSoA候補列とOpenCL競合裁定を使用します。Settled Distributionは表面接続Guide Fieldを訪問済み三角形の3頂点でキャッシュし、候補位置へ決定的に補間します。Finalの候補ごとのCPU exact評価とStable Cell ID契約は維持します。

`bifrost_scales_candidate_batch_benchmark` で候補数、転送bytes、生成時間を計測できます。

Native CoreはDistribution、Orientation、Cell、ShapeをC++17で評価します。

0.10.6は全Cell共通のRay角度表、Sample Normal／Surface Componentの事前計算、Mask Guideなし高速経路、1 Sample = 1 Partition Siteの直接制約を追加します。Cell Direction Anisotropy=0では等方Cell境界計算を維持します。非0ではGuide別Cell Anisotropyと最大2.25軸比の上限付き異方性を使用し、Center Alignmentは中心候補数を独立制御します。

Interactive／Direction Relax 0のOrientationだけをOpenCL GPUへオフロードできます。OpenCLは動的ロードされ、失敗時はマルチコアCPUへ戻ります。Settledは倍精度CPUの決定的な三角形Field補間、Finalは候補ごとの倍精度CPU exactです。Interactive Distributionの候補競合はOpenCLへ接続済みで、利用不可時は同じ優先規則のCPU referenceへ戻ります。

開放エッジ境界アンカーは局所Densityの平方根で重み付けしたArc Lengthへ配置します。neutral Densityは0.10.2互換です。

```text
Core version        0.10.6
Payload             bifrost-scales/native-payload/10
Operator            bifrost-scales/operator-contract/18
Behavior            bifrost-scales/native-core/0.10.6-settled-field-cache-1
Profile             bifrost-scales/native-profile/9
GPU Buffer          bifrost-scales/compact-orientation-buffer/2
```

ビルドにはC++17、Threads、Bifrost SDKが必要です。OpenCL SDKは不要です。
