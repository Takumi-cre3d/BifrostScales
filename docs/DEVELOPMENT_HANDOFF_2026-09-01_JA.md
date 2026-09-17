# MayaScales 開発引き継ぎ — 2026-09-01

## 1. この資料の目的

この文書は、新規チャットが過去ログを読まなくてもMayaScalesの開発を安全に再開できるよう、現在の正本、確定仕様、検証結果、保護資産、製品版UI/UX要件、最初の作業手順をまとめたものです。

次の開発対象は製品版UI/UXです。0.10.9 Public BetaのNative生成結果、Stable Cell ID、決定性、Scene互換性を変更してはいけません。

## 2. 新規チャットへ渡す開始指示

```text
D:\TA-Tools\MayaScales のMayaScales開発を引き継いでください。
最初に docs/DEVELOPMENT_HANDOFF_2026-09-01_JA.md を全文読み、続いて
docs/UI_UX_PRODUCT_HANDOFF_JA.md、BUILD_INFO.json、docs/ARCHITECTURE_JA.md、
docs/ROADMAP_JA.mdを確認してください。

0.10.9 Public Betaの生成結果、Stable Cell ID、決定性、Payload／Operator／Profile
契約 10 / 20 / 11、既存Scene互換を固定してください。

最初の実装はUIの見た目変更ではなく、Slider Drag中の評価回数、Interactive／Settled
遷移、Main Thread停止時間を同一入力で測る再現テストから始めてください。

dragon.mb、incrementalSave/、ルートBifrostScales.modはユーザー資産です。
削除、上書き、commitをしないでください。
```

## 3. 現在のGit正本

- Repository: `https://github.com/Takumi-cre3d/BifrostScales`
- Branch: `main`
- HEAD: `1a29a1cf87a49666a432b8c90285fc0c2c5c87ae`
- Merge PR: `#28 Release Bifrost Scales 0.10.9 Public Beta`
- CI: run `232`成功
- Version: `0.10.9`
- Release channel: `beta`
- Maya: `2026`
- Bifrost: `2.15`

ローカル`main`と`origin/main`は上記SHAで一致しています。ただし、作業ツリーには意図的に保護しているローカル資産が残っています。

```text
 M BifrostScales.mod
?? dragon.mb
?? incrementalSave/
```

これらを作業開始時の「不要な差分」と判断して復元・削除してはいけません。

## 4. Public Beta成果物

- ZIP: `dist/BifrostScales_0_10_9_Beta_OneClick_Installer.zip`
- Checksum: `dist/BifrostScales_0_10_9_Beta_OneClick_Installer.zip.sha256`
- ZIP SHA-256: `1d40dcef31079297955f206c57dbbb1fcc3034f466527bc515fdcca8c943ee9d`
- Native DLL SHA-256: `c9714eb6fd97a6448f8f4aecaf58f4f4285d5e1dbad7f4d223d46a1a463155fe`
- Payload files: `45`

GitHub Releaseとしての一般公開操作はまだ行っていません。現在あるのは、公開可能なローカル成果物とmainへマージ済みの再現可能な生成ソースです。

旧名`BifrostScales_0_10_9_OneClick_Installer.zip`とchecksumは、Beta版との取り違えを防ぐため削除済みです。必要なら旧Git履歴から再生成できます。

## 5. Installer／Uninstaller契約

### Install

- `Install_BifrostScales.cmd`をダブルクリックする
- Maya 2026付属`mayapy.exe`を優先する
- Windows x64、Maya 2026、Bifrostを確認する
- Payloadをコピー前後にSHA-256検証する
- 既存PackageとModule定義を日時付きBackupへ移す
- 失敗時は以前の状態へロールバックする

### Uninstall

- `Uninstall_BifrostScales.cmd`をダブルクリックする
- Activeな`BifrostScales/`と`BifrostScales.mod`だけを対象にする
- 削除ではなく日時付きRecoveryへ移動する
- Maya Scene、制作データ、設定、既存Backupには触れない
- 既に未導入の状態で再実行しても成功する
- 途中失敗時はActive状態へロールバックする

実装は別系統を増やさず、`installer/offline_install.py`のInstall／Uninstallを共通Launcherから呼ぶ構成です。

## 6. 確定アーキテクチャ

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
Maya Viewport 2.0
```

PythonはUI、Scene管理、Guide、設定、Picker、Bifrost Graph接続を担当します。鱗生成の正本はNative C++ Operatorです。Python Reference RuntimeやPython Final Bakeへ戻してはいけません。

## 7. 固定する製品契約

- Runtime: Native-only
- Graph: immutable published graph v4
- Payload Schema: `bifrost-scales/native-payload/10`
- Operator Contract: `20`
- Native Profile Schema: `bifrost-scales/native-profile/11`
- Scene Schema: `bifrost-scales/5`
- Settled／Final: 決定的CPU exact
- Interactive: OpenCL GPUを使用可能、失敗時はCPUへ自動fallback
- Direction Relax: CPU exact
- Stable Cell IDとCell境界: GPU結果を正本にしない
- Stage Cache: `process-shared-bounded/2`
- Guide Surface Field: Guideごとに再利用する
- Interactive Mesh Sampling: Target geometryごとに再利用する
- Settled Grid density floor: `0.04`
- Triangle proposal lookup: `65,536` bin index

GPU最適化のためにSettled／Finalのルック、Stable ID、Cell境界、既存Scene出力を変更してはいけません。

## 8. 0.10.9までに完了した主な開発

- Native-only Runtimeへの移行
- 決定的マルチコアCPU生成
- OpenCL Interactive Orientation
- Interactive Candidate BatchとCPU Reference arbitration
- GPU Candidate Conflict arbitration
- CPU／GPU Candidate Key・受理Index一致
- Guide Surface Field cache
- Interactive Target Mesh sampling cache
- Orientation非依存Cell cache
- exact Cell Partition hot path
- 開放エッジDensity対応
- 高曲率Cellのexact再投影
- Density過密時のGap／Collision Margin制限
- `dragon.mb`からNative parity入力を決定的にexportするTool
- Settled DistributionのProposal indexとGrid密度改善
- Public Beta Installer／Uninstaller

## 9. 性能基準

0.10.9のSettled Grid density floorを`0.08`から`0.04`へ変更しました。同一Sample、Stable Cell ID、決定的Settled結果を維持したまま、ユーザー操作ログでは次の改善を確認しています。

- Distribution中央値: `442.07 ms` → `416.71 ms`
- Distribution最大値: `674.43 ms` → `455.48 ms`
- Total最大値: `1014.3 ms` → `796.6 ms`
- Bifrost v142中央値: `1390.947 ms` → `1261.128 ms`

性能評価では中央値だけでなく最大値、Cold／Cache Hit、`distribution_bucket_queries`、`distribution_distance_tests`、`distribution_grid_density_reference`を記録してください。

`dragon.mb`は実シーン回帰の正本です。Scene自体はGitへ追加しません。

## 10. Beta最終検証

- Native clean Maya 2026／Bifrost 2.15 build: 成功
- Native CTest: `2 / 2`
- Clean CI Python: `155 / 155`
- 開発PC Python: `154`件成功
- Schema Audit: `50 / 50`
- Native-only Audit: `12 / 12`
- Cell Picker Audit: `18 / 18`
- Release Consistency Audit: `16 / 16`
- Bundle決定性: 同一ソースから同一ZIP SHA
- 隔離Bundle: 新規、更新、Backup、Uninstall、二重Uninstall、再Install成功
- 実ユーザーmodules: Public CMDからInstall／Uninstall成功
- Source／Installed DLL hash: 一致
- Maya headless: `bifrostGraph`明示Load後、`ready=True`、契約チェック`13 / 13`

開発PCでは配布用Native Packがソースツリーに存在するため、「Pack未構築」を前提とするテスト1件だけを除外します。Clean CIでは全155件が通ります。

Maya headless起動時に、MayaUSD／PySide由来のNumPy 1.x対2.3.3警告やMenu関連警告が出ることがあります。Bifrost Scalesの最終13項目がTrueであれば、これらを本製品の失敗と混同しないでください。

## 11. 製品版UI/UXで解決する問題

1. Slider Drag中の連続評価によるポインターとViewportのカクつき
2. Guide一覧の階層、複数選択、並べ替え、Inline Rename不足
3. Groupが1層のみで、作成、移動、整理が重い
4. GuideとScale Typeのリンク導線が遠く、関係を一覧で把握しにくい
5. パラメータ数が多く、優先度、単位、依存関係が分かりにくい
6. Preview上限をSceneごとに手動調整する必要がある
7. 鱗形状を多数のSliderだけで調整している
8. 余白、整列、配色、状態表示、文言の一貫性が不足している

詳細仕様と受け入れ条件は`docs/UI_UX_PRODUCT_HANDOFF_JA.md`を正本とします。

## 12. UI/UX開発の優先順序

1. 現行Widget、Callback、Undo、Graph評価経路を計測する
2. Slider要求を集約し、Drag中Interactive、Release後Settled 1回へする
3. Guide OutlinerのScene正本、複数選択、階層、Rename、順序保存を実装する
4. GuideとScale Typeの関係表示、一括Assign、Jumpを実装する
5. Parameter Section、文言、Tooltip、Design Tokenを整理する
6. Preview Budget AutoとManual Overrideを実装する
7. 幅／厚みの2軸Curve UIと旧Scalar互換を実装する
8. アーティスト操作テスト、回帰、Installer更新を行う

最初から全UIを書き直さず、現在のScene／Backend契約を保ったまま計測可能な境界から分割してください。

## 13. UI/UXの重要な受け入れ条件

- Drag中にSettledを実行しない
- Mouse Release後のSettledは1回だけ
- Drag 1回をUndo 1回にまとめる
- 古いInteractive要求を破棄し、最新値だけを評価する
- Guide多階層Groupの順序とCollapse状態を保存・再読込できる
- Maya、Viewport、Guide一覧の選択を同期する
- Guide行だけでScale Typeとの対応を識別できる
- Auto PreviewがSettled Budget、Stable ID、最終ルックを変えない
- Curve既定値が旧Scalar形状とGolden一致する
- 旧Sceneを開いた直後のSettled MeshとStable IDがBeta基準と一致する
- Keyboard、Focus、文字切れ、High-DPIをMaya 2026で検証する

## 14. 変更禁止・後回し

- UI/UX作業と同時にNative生成アルゴリズムを変更しない
- Payload／Operator／Profile Schemaを理由なく更新しない
- Stable Cell IDやScene Schemaを作り直さない
- GPU PreviewをSettled／Finalの正本にしない
- Final／Bakeを契約と実機検証なしに公開しない
- Cell／Shape GPU化や常駐GPU Bufferを1.0必須要件にしない
- 新しい依存関係や抽象化を、測定できる必要性なしに追加しない

## 15. Repository案内

- `BifrostScales/scripts/bifrost_scales/ui.py`: メインUI
- `BifrostScales/scripts/bifrost_scales/backend.py`: UIとNative Graphの境界
- `BifrostScales/scripts/bifrost_scales/native_backend.py`: Native契約、Probe、Graph評価
- `BifrostScales/scripts/bifrost_scales/scene.py`: Scene正本
- `BifrostScales/scripts/bifrost_scales/guides.py`: Guide／Group authoring
- `BifrostScales/scripts/bifrost_scales/cell_picker_maya.py`: Picker runtime
- `native/src/core.cpp`: Native生成本体
- `native/src/gpu_compute.cpp`: OpenCL実行
- `native/bifrost/operator_contract.json`: Operator契約
- `tools/build_one_click_installer.py`: Public Bundle生成
- `installer/offline_install.py`: Transactional Install／Uninstall
- `tools/export_maya_parity_case.py`: Maya Scene parity入力export
- `tests/`: Python回帰
- `native/tests/`: Native回帰

## 16. 最初に読む資料

1. `docs/DEVELOPMENT_HANDOFF_2026-09-01_JA.md`
2. `docs/UI_UX_PRODUCT_HANDOFF_JA.md`
3. `BUILD_INFO.json`
4. `docs/ARCHITECTURE_JA.md`
5. `docs/ROADMAP_JA.md`
6. `docs/ONE_CLICK_INSTALLER_JA.md`
7. `docs/MAYA_HOST_TEST_JA.md`
8. `docs/NATIVE_VALIDATION_JA.md`

## 17. 開発開始時の安全確認

```powershell
git status --short --branch
git log -3 --oneline --decorate
Get-FileHash -LiteralPath BifrostScales.mod -Algorithm SHA256
```

期待するローカルModule SHA-256:

```text
6BADDD2D278243BD7EC3B337FE46F9ABAC5C2082C9E691B3447268B36906D287
```

Native PackをBuildするとルート`BifrostScales.mod`が上書きされることがあります。Build前にSHA付きで退避し、成功・失敗に関係なく`finally`相当で復元してください。

Maya headless検証では、`ready=False`を判断する前に`bifrostGraph`を明示Loadしてください。

## 18. 検証の原則

- 変更前後で同じScene、入力、Frame、設定、評価条件を使う
- UI変更でも生成Mesh、Stable ID、Payloadを比較する
- Slider改善は主観だけでなく評価回数とMain Thread停止時間を記録する
- Scene保存・再読込、Undo／Redo、Maya再起動まで検証する
- Sourceテストだけで終えず、最終的にインストール済み製品経路で確認する
- 長いログは保存し、報告では件数、失敗、警告、時間、パスを要約する

## 19. 完了の定義

各UI/UX変更は、次のすべてを満たして初めて完了です。

1. 対象操作の問題を同一入力で再現できる
2. 変更後に測定値または操作手順が改善している
3. Betaの生成結果、Stable ID、Scene互換が維持される
4. Unit／Contract／Host検証が通る
5. 実Maya上でアーティスト操作として確認できる
6. 必要な仕様と検証手順が文書またはTestへ反映される

## 20. 次の具体的な一手

`main`から`codex/ui-ux-product`などの専用Branchを作り、Sliderを1回Dragした際に次を記録する小さな再現Harnessを先に作ります。

- valueChanged／sliderMoved／sliderReleased callback回数
- Native Graph publish回数
- Interactive評価回数
- Settled評価回数
- Main Threadの最長停止時間
- Undo Queueへ積まれるCommand数

この測定を変更前Baselineとして保存し、要求集約後に同一Drag入力で比較してください。その後、同じ評価状態機械をGuide／Scale Type編集へ広げます。
