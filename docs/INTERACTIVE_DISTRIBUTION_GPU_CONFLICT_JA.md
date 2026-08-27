# Interactive Distribution GPU Conflict Arbitration

## 目的

`bifrost-scales/interactive-conflict-gpu/1` は、CPU referenceと同じCandidate ordinal優先規則をOpenCL上で再現するHost非依存Contractです。Maya Runtimeへ接続する前に、GPU Buffer、決定性、CPU fallback、性能Crossoverを固定します。

## Algorithm

1. Host側でCandidateのGrid Cellと全Candidate用Hash Gridを構築します。
2. Density／Mask gateをCandidate単位で並列評価します。
3. 未決定Candidateのうち、競合する低ordinal未決定Candidateを持たないCandidateを同一RoundのWinnerとして並列選択します。
4. WinnerをAcceptし、Winnerと競合する未決定CandidateをRejectします。
5. 未決定Candidateがなくなるまで3～4を繰り返します。
6. Candidate ordinal順に結果をcompactし、受理上限までのIndex／KeyとRejectカウンタを出力します。

このParallel Lexicographic MISは、CPU referenceの逐次Greedy優先規則と同じ受理集合・順序を維持します。Hash Bucketの列挙順には依存しません。

## GPU Policy

- `BIFROST_SCALES_GPU=off`: CPU referenceを使用
- `BIFROST_SCALES_GPU=auto`: 既定8,192候補以上でGPUを試行
- `BIFROST_SCALES_GPU=force`: 候補数に関係なくGPUを試行
- `BIFROST_SCALES_GPU_MIN_CANDIDATES`: Auto Crossoverを上書き

OpenCL Runtime／GPUがない場合、Buffer作成、Kernel build／execution、readback、出力検証のいずれかが失敗した場合はCPU referenceへ戻ります。最大4,096 Roundで収束しない入力もCPUへfallbackします。

## Runtime境界

このContractはMaya RuntimeのInteractive Distributionへ接続済みです。Settledは決定的CPU三角形Guide Field Cache、Final／Bakeは候補ごとのCPU exactを使用し、Cell境界はCPUで評価します。

## 検証

- MSVC Release build: PASS
- Native tests: 2／2 PASS
- Default／可変Spacing／極小Spacing／全域競合: CPU/GPU完全一致
- Seed 1～8 parity sweep: PASS
- 40,000候補: 7,511受理、5 Round、CPU/GPU Index／Key／Rejectカウンタ完全一致
- 100,000候補: CPU/GPU完全一致
- 200,000候補: CPU/GPU完全一致

RTX 4070 Ti SUPERでの5回中央値は次のとおりです。

| Candidates | CPU reference | GPU accelerated wall | GPU kernel |
|---:|---:|---:|---:|
| 40,000 | 7.550 ms | 6.087 ms | 3.169 ms |
| 100,000 | 17.416 ms | 13.377 ms | 7.696 ms |
| 200,000 | 34.513 ms | 25.730 ms | 14.919 ms |

40,000候補ではEnd-to-End Arbitrationが約19.4%短縮しました。値にはCandidate生成時間を含まず、GPU accelerated wallにはHost Grid構築、upload、Kernel、Round同期、readbackを含みます。性能値は開発機での参考値であり、製品性能保証ではありません。

## 次段階

Interactiveから決定的SettledへのStable ID／画面差分を継続測定し、Final exactへの切替契約を定義します。
