# Bifrost Scales Roadmap — 0.10.6以降

## 完了

- Native-only Runtime
- 決定的マルチコアCPU
- Orientation非依存Cell Cache
- 0.10.3 Guide Dirty Region撤回、0.10.2全Orientation更新へ復帰
- OpenCL Interactive Orientation GPU Compute
- GPU自動CPUフォールバック
- Density連動の開放エッジ境界アンカー
- exact Cell Partition Hot Path

## 次段階

1. Candidate Batch上のCPU Reference Conflict Arbitration
2. GPU上のCandidate Conflict Arbitration
3. CPU exact SettleとのStable ID／画面差分測定
4. Cell／Shape用Compact Parameter Buffer
5. GPU Procedural Cell Preview
6. Viewport常駐Bufferと再Upload削減
7. 対象GPUでの自動Crossover学習

## 開発再開で追加済み

- `bifrost-scales/interactive-candidate-batch/1`
- Compact SoA（1候補72 bytes）
- Counter-based deterministic stream
- Count増加時のprefix安定性
- Settled CPU exact経路からの完全分離

Stable Cell ID、Cell境界、Settled／Final／BakeはCPU exactの正本を維持します。DistributionのFieldだけを部分移植せず、Candidate生成と競合解決を一括したPreview経路として測定します。GPU対応のために簡易形状へ置換したり、最終ルックを変更したりしません。
