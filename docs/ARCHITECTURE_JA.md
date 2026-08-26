# Bifrost Scales Architecture — Native-only 0.10.6

```text
Maya Python Host
  UI / Scene / Guide / Settings / Picker
            |
            | payload_json + TargetShape.worldMesh[0]
            v
Immutable Published Bifrost Graph v4
            |
            v
BifrostScales Native C++ Operator
  Distribution        CPU exact
  Interactive Orient  OpenCL GPU または CPU fallback
  Settled/Final Orient CPU exact
  Cells / Shape / IDs CPU exact
            |
            v
Geometry::Mesh::construct_mesh
            |
            v
Maya Viewport 2.0 GPU display
```

## Guide更新境界

0.10.3の局所Dirty Regionは撤回済みです。0.10.6は0.10.2と同じ全Orientation更新を行い、Distributionと正確なCell PartitionをStage Cacheで再利用します。Cell MISS時は共通Ray表、事前計算済みNormal／Component、Maskなし高速経路を使います。

## OpenCL GPU

OpenCL 1.2を実行時に動的ロードします。OpenCL DLLやGPU Deviceを取得できなくてもOperatorロードは失敗せず、同じ入力をマルチコアCPUで評価します。

GPU入力はSample位置、法線、Random Rotation、Direction Guide、Curve Segmentをまとめた`bifrost-scales/compact-orientation-buffer/2`です。GPU出力はOrientation Tangent、Cell Partition Tangent、Direction Influence、Cell Anisotropy Influenceです。

GPU float計算は操作中表示だけに限定します。Settled／Final、Direction Relax、Cell境界、Stable Cell IDは倍精度CPU exactなので、GPU固有の丸めが制作データの正本にはなりません。

## 開放エッジ

境界Chainの物理長を`sqrt(local density)`で重み付けし、重み付き距離上へアンカーを等間隔配置します。局所希望間隔は`base spacing / sqrt(local density)`です。これにより、低Densityで境界アンカーだけが強制過密化する状態を防ぎます。
