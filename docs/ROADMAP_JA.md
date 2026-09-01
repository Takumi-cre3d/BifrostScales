# Bifrost Scales Roadmap — 0.10.9以降

現在のNative生成機能を0.10.9 Public Betaとして固定し、製品版UI/UXは`UI_UX_PRODUCT_HANDOFF_JA.md`の別開発へ移します。

## 完了

- Native-only Runtime
- 決定的マルチコアCPU
- Orientation非依存Cell Cache
- 0.10.3 Guide Dirty Region撤回、0.10.2全Orientation更新へ復帰
- OpenCL Interactive Orientation GPU Compute
- GPU自動CPUフォールバック
- Density連動の開放エッジ境界アンカー
- exact Cell Partition Hot Path
- Interactive Candidate Batch
- Candidate Batch上のCPU Reference Conflict Arbitration
- GPU Candidate Conflict Arbitration
- CPU／GPU受理Index・Candidate Key完全一致
- 65,536候補の自動GPU CrossoverとCPU fallback
- `dragon.mb` Native parity入力の決定的export
- Settled Grid密度下限0.04（同一Sampleを維持し、Bifrost v142中央値を1,390.947 msから1,261.128 msへ短縮）
- Maya操作ログでDistribution中央値を442.07 msから416.71 ms、最大値を674.43 msから455.48 msへ短縮

## Interactive Distribution基盤

- `bifrost-scales/interactive-candidate-batch/1`
- `bifrost-scales/interactive-conflict-reference/1`
- Compact SoA（1候補72 bytes）
- Counter-based deterministic stream
- Count増加時のcandidate／arbitration prefix安定性
- Density／Mask stochastic gate
- Candidate単位Local Spacingと決定的な空間競合裁定
- Settled CPU exact経路からの完全分離
- Parallel Lexicographic MISによるCPU優先規則の再現

## 製品版到達方針

新機能より、再現性・互換性・配布品質を優先します。Stable Cell IDとCell境界は決定的CPU処理を維持し、Settledをルック開発の正本とします。GPU対応のために簡易形状へ置換したり、最終ルックを変更したりしません。

### P0: リリース阻害要因

1. 同一入力でInteractive／SettledのStable ID、枚数、画面差分を継続測定する
2. 今回のInteractive／Settled操作ログを製品版性能基準として保存し、以後は同条件で回帰比較する
3. Maya 2026／Bifrost 2.15の実環境で新規、更新、再起動、アンインストールを検証する
4. クリーンなソースからNative Packとワンクリックインストーラーを再現生成する
5. 旧版成果物と開発者ローカル資産を公開物へ混入させない

### P1: 品質固定

1. Guide 3種、Point、D／S、低密度、急曲率、境界、高密度を実シーン回帰ケースとして固定する
2. Cold／Cache Hitの両方を記録し、中央値だけでなく遅いケースも追跡する
3. README、移行手順、既知の制限、復旧手順を製品版の実挙動へ揃える
4. Final／BakeはNative exact契約とホスト検証が揃うまで公開しない

### リリース判定

- Native CTest、Pythonテスト、Schema／Native-only／Picker／Release監査がすべて成功する
- 同一入力の決定性、CPU／GPU parity、InteractiveからSettledへの切替互換を確認する
- 生成したPackとインストール済みDLLのハッシュが一致する
- Maya実機ログでGraph publish、再起動後のCatalog、代表シーンの生成を確認する
- 公開ZIPを隔離ディレクトリへインストールし、更新時バックアップとアンインストールを再検証する

## 製品版後の候補

1. Cell／Shape用Compact Parameter Buffer
2. GPU Procedural Cell Preview
3. Viewport常駐Bufferと再Upload削減
4. 対象GPUごとの自動Crossover調整

これらは1.0の必須条件にせず、現行の決定性とルックを維持できる測定結果が揃ってから着手します。
