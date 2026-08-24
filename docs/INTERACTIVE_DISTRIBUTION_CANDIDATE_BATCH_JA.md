# Interactive Distribution Candidate Batch

## 目的

GPU Distributionへ進む前に、候補生成と競合解決を分離できる転送契約を追加しました。現行CPU exact Poisson列は条件分岐に応じて乱数消費位置が変わるため、Field計算だけのGPU移植では競合解決と同期コストを除去できません。本契約はInteractive Preview専用の独立ストリームです。

## Contract 1

`bifrost-scales/interactive-candidate-batch/1` は次のSoA Bufferを持ちます。

- Position XYZ: float32 x 3
- Normal XYZ: float32 x 3
- Barycentric: float32 x 3
- Random: float32 x 6（Density acceptance、Mask acceptance、Size、Rotation、Type、Shape）
- Triangle Index: uint32
- Candidate Key: uint64

1候補72 bytesです。カウンタベースRandomにより同じMesh／Seed／Countはbyte-stableです。Countを増やしても既存prefixは変化しません。

## 非目標

- 現行 `distribute()` の置換
- Boundary Anchor／Guide Center AnchorのGPU化
- GPU Candidate Conflict Arbitration
- Settled／Final／Bakeの変更
- Stable Cell IDの正本変更

## 受入結果

- MSVC Release build: PASS
- Native deterministic test: PASS
- 32候補のrepeat一致: PASS
- 32→128候補のprefix一致: PASS
- Candidate Key一意性: PASS
- 呼び出し前後のSettled vertices／faces／cell_ids一致: PASS
- 40,000候補: 2,880,000 bytes、4.126 ms（単回参考値）

次段階は、Guide Field評価を同じBatchへ適用し、Candidate Key順の競合解決をCPU referenceとして定義してからGPU版と比較することです。
