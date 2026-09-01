# Native Runtime Validation — Bifrost Scales 0.10.9

## 必須検証

```text
Python regression
Native Release core tests
Native -Wall/-Wextra/-Wpedantic/-Werror
ASan / UBSan
ThreadSanitizer
Schema Contract Audit
Native-only Runtime Audit
Cell Picker Audit
Release Consistency Audit
Extracted-source再検証
```

## GPU検証境界

- `BIFROST_SCALES_GPU=off`: InteractiveがCPUで正常生成される
- `force`: OpenCL GPUを試行し、成功時はOrientation Worker 0
- GPUなし／OpenCLなし／Kernel失敗: CPUへ自動フォールバック
- Direction Relax > 0: CPU exact
- Settled: 環境変数`force`でも決定的CPU三角形Field Cache
- Final: 環境変数`force`でも候補ごとのCPU exact
- Settled CPU offとforce: 頂点、Face、Stable Cell IDが完全一致

Profile 10はGPU request、availability、device、upload/kernel/readback時間、fallback reason、境界Density適応、プロセス共有Stage Cache状態に加え、`guideSurface=時間(hit/miss)`とInteractiveの`meshSample=hit|miss`を出力します。Settled／Finalの`meshSample`表示は`n/a`です。

このLinux検証環境にはOpenCL GPU Platformがないため、GPU実行時間はMaya対象PCで測定します。CPU fallback、Settledの決定性、Final exactはホスト非依存テストで検証します。
