# Bifrost Scales Architecture — Native-only 0.10.9

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
  Distribution        Interactive OpenCL / Settled CPU Field Cache / Final CPU exact
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

0.10.3の局所Dirty Regionは撤回済みです。0.10.9は全Orientation更新を行い、Distributionと正確なCell PartitionをStage Cacheで再利用します。Surface Guide FieldはTarget geometryとGuide geometry／radiusでGuide別にkey化した上限付きCacheへ保存し、Guideを1本編集した場合はそのFieldだけを再構築します。全Fieldがhitする評価ではGuide投影用の全体BVH構築を省略します。Interactive DistributionはTarget geometryでkey化した三角形面積累積表と法線を再利用します。Cell MISS時は共通Ray表、事前計算済みNormal／Component、Maskなし高速経路を使います。

## Cell曲面追従

Cell段階は外周端点に加えて各Rayの中点と法線をTarget表面へ投影し、Cell Cacheへ保持します。Shape段階は中心・中点・外周の二次補間で内側リングを曲面へ沿わせます。相対サグ量が0.001を越えるか、Sample法線から約3度を越えて曲がるCellは、Width／Length／Forward等のShape変形後に内側リングと中心を接続局所表面へexact再投影します。

GapとCollision Marginは従来どおりworld-spaceの共有幅ですが、強いDensity Guideで中心間隔より広くなる場合は、所有SeedをPartition外へ押し出さない最大値へpair単位で制限します。これによりCell Cacheや中心配置を変更せず、局所的な巨大fallback Cellだけを防ぎます。

## OpenCL GPU

OpenCL 1.2を実行時に動的ロードします。OpenCL DLLやGPU Deviceを取得できなくてもOperatorロードは失敗せず、同じ入力をマルチコアCPUで評価します。

GPU入力はSample位置、法線、Random Rotation、Direction Guide、Curve Segmentをまとめた`bifrost-scales/compact-orientation-buffer/2`です。GPU出力はOrientation Tangent、Cell Partition Tangent、Direction Influence、Cell Anisotropy Influenceです。

GPU float計算は操作中表示だけに限定します。Settled、Final、Direction Relax、Cell境界、Stable Cell IDはCPUで決定的に評価されます。Settled Distributionのみ三角形Guide Field補間を使い、Finalは候補ごとの倍精度exact評価を維持するため、GPU固有の丸めが制作データの正本にはなりません。

## 開放エッジ

境界Chainの物理長を`sqrt(local density)`で重み付けし、重み付き距離上へアンカーを等間隔配置します。局所希望間隔は`base spacing / sqrt(local density)`です。これにより、低Densityで境界アンカーだけが強制過密化する状態を防ぎます。
