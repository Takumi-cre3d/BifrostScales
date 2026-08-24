# Interactive Distribution Candidate Batch／Conflict Reference

## 目的

Interactive DistributionのGPU実装に先行して、Surface Candidate生成、Guide Field入力、競合裁定を独立した転送契約として定義します。現行CPU exact Poisson列とは分離し、Settled結果とStable Cell IDの正本を維持します。

## Candidate Batch Contract

`bifrost-scales/interactive-candidate-batch/1` は次のSoA Bufferを持ちます。

- Position XYZ: float32 x 3
- Normal XYZ: float32 x 3
- Barycentric: float32 x 3
- Random: float32 x 6（Density acceptance、Mask acceptance、Size、Rotation、Type、Shape）
- Triangle Index: uint32
- Candidate Key: uint64

1候補72 bytesです。Counter-based Randomにより同じMesh／Seed／Countは決定的です。Countを増やしても既存prefixは変化しません。

## Conflict Reference Contract

`bifrost-scales/interactive-conflict-reference/1` は将来のGPU Passと比較するHost非依存CPU referenceです。

1. Candidate ordinalの昇順を優先度として処理します。
2. Density RandomとMask Randomが各acceptance未満の場合だけ競合判定へ進みます。
3. `local_spacing` が省略された場合はSurface Area、受理上限、Spacing Factorから既定値を計算します。
4. Candidateと既受理Candidateの距離が両者のLocal Spacingの最大値未満なら競合Rejectします。
5. 受理上限へ到達するかCandidate末尾へ到達すると終了します。

Field配列はCandidate数と同じ長さ、または空配列です。空のDensity／Mask acceptanceは1、空のLocal Spacingは既定値を表します。結果には受理Candidate Index／KeyとDensity、Mask、Conflict別のReject数を保存します。

空間Indexは最大Local SpacingをCell Sizeとする3D Gridです。Gridの走査順とCandidate処理順は固定し、Hash Mapのiteration orderには依存しません。

## 非目標

- 現行 `distribute()` の置換
- Maya Runtimeへの接続
- Boundary Anchor／Guide Center AnchorのGPU化
- GPU Candidate Conflict Arbitration
- Settled／Final／Bakeの変更
- Stable Cell IDの正本変更

## 検証結果

- MSVC Release build: PASS
- Native tests: 2／2 PASS
- Arbitration repeat一致: PASS
- 512→2,048候補の受理prefix一致: PASS
- Density／Mask gate境界: PASS
- 可変Local Spacing: PASS
- 呼び出し前後のSettled vertices／faces／cell_ids一致: PASS
- Python tracked tests: 140 PASS
- 40,000候補: 2,880,000 bytes、Candidate生成中央値4.207 ms、Conflict Arbitration中央値7.653 ms、受理7,511件

性能値はWindows／MSVC Releaseで5回測定した参考中央値であり、製品性能保証ではありません。

次段階は、同じBufferと判定規則をGPUへ移植し、受理Index／Candidate KeyをCPU referenceと比較することです。
