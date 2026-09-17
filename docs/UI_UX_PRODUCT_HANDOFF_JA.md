# MayaScales 製品版UI/UX開発 引き継ぎ

## 目的

0.10.9 Public BetaのNative生成結果、Stable Cell ID、決定性、Maya 2026／Bifrost 2.15契約を維持したまま、アーティストが迷わず軽快に操作できる製品UIへ再設計します。UI/UX開発は新規スレッドで行い、Betaへの変更は重大な不具合修正に限定します。

## Betaで固定する正本

- Settledは決定的CPU結果、Interactiveは軽量Preview
- Payload／Operator／Profile契約は`10 / 20 / 11`
- InteractiveからSettledへの切替でStable Cell IDと最終ルックを守る
- Guide、Group、Scale Type、既存Sceneの後方互換を維持する
- `dragon.mb` parity入力とNative Profileログを性能回帰の基準にする

## Betaリリース基準

- 配布物: `dist/BifrostScales_0_10_9_Beta_OneClick_Installer.zip`
- ZIP SHA-256: `1d40dcef31079297955f206c57dbbb1fcc3034f466527bc515fdcca8c943ee9d`
- Native DLL SHA-256: `c9714eb6fd97a6448f8f4aecaf58f4f4285d5e1dbad7f4d223d46a1a463155fe`
- Native CTest `2 / 2`、クリーンCI Python `155`件、Schema `50 / 50`、Native-only `12 / 12`、Picker `18 / 18`、Release `16 / 16`を通過
- Public Bundleで新規導入、更新Backup、復旧可能なアンインストール、二重アンインストール、再導入を検証済み
- Maya 2026で`bifrostGraph`を明示ロードし、実ユーザーmodulesから`ready=True`と全Native契約を確認済み

開発PCでは配布用Packをソースツリー内に構築済みのため、「Pack未構築」を前提とする1件だけを除外し、Python `154`件が通過します。クリーンCIでは全`155`件が通過することをリリース条件にします。

## 現在の問題

1. Slider操作中に評価が連続し、ポインター追従とViewportがカクつく
2. Guide一覧がOutlinerとして弱く、階層、複数選択、並べ替え、リネームが扱いにくい
3. Groupが1層に限られ、作成・移動・整理の操作が重い
4. GuideとScale Typeのリンク導線が遠く、対応関係を一覧で把握しにくい
5. パラメータ数が多く、優先度、依存関係、単位、効果を理解しにくい
6. Preview上限を手動調整する必要があり、シーン規模ごとの判断負担が大きい
7. 鱗形状を多数のSliderで作るため、RootからTipまでの形状意図を直接編集しにくい
8. 余白、整列、配色、状態表示、文言の一貫性が不足している

## 製品版要件

### 1. SliderとPreview

- Drag中はInteractiveだけを使用し、古い要求を破棄して最新値へ集約する
- 同時評価は1件までとし、Mouse ReleaseでSettledを1回だけ実行する
- 1回のDragをUndo 1回にまとめる
- 計算中、未確定、Settled完了をUIとViewportで区別する
- 同一入力でPointer追従、評価回数、Interactive／Settled時間を計測可能にする

### 2. Guide Outliner

- Maya Outlinerに近い複数選択、Shift／Ctrl選択、Inline Rename、検索、表示／Lockを提供する
- Groupの多階層化、Drag & DropによるReparent／並べ替え、Collapse状態保存に対応する
- 作成、複製、削除、Group化を選択位置のContext MenuとShortcutから実行できる
- Maya Scene選択、Viewport選択、Guide一覧選択を同期する
- 大量Guideでも全件再構築を避け、変更された行だけを更新する

### 3. GuideとScale Typeの関係

- 各Guide行にScale Type名、色、未割当状態を表示する
- Guide側からAssign／変更／解除、Scale Type側から使用Guideの絞り込みとJumpを可能にする
- Drag & DropまたはContext Menuで複数Guideへ一括Assignできる
- 削除、Rename、Duplicate時の参照更新と警告を定義する

### 4. パラメータ構成

- 初期画面は主要パラメータだけにし、Advancedを段階開示する
- Label、単位、Tooltip、Reset、既定値、影響Stageを一貫表示する
- 相互依存パラメータは同じSectionへ置き、無効な組み合わせは理由付きでDisableする
- Presetは単なる数値コピーとし、Scene固有の非表示状態を作らない

### 5. Preview上限のAuto化

- Mesh規模と直近Interactive時間からPreview Budgetを自動選択する
- Manual Overrideを残し、Autoが選んだ値と理由を表示する
- Settled Budget、Stable Cell ID、最終ルックへ影響させない
- 急な品質変化を避け、同じ操作中はBudgetを安定させる

### 6. 鱗形状Curve UI

- Sweep MeshのTaper Curveを参考に、Root→Tipの正規化軸を持つ2本のCurveを提供する
- 1本は幅、1本は厚み／側面形状を制御し、Viewportへ即時反映する
- Point追加、削除、移動、Reset、数値編集、Copy／Pasteを提供する
- 現行Scalar設定を既定Curveへ変換し、旧Sceneの見た目を変えない
- Curve値の保存Schema、補間、Clamp、Mirrorの仕様を実装前にGolden Testで固定する

### 7. Visual Design

- 情報階層、余白、行高、Label幅、Icon、Focus／Hover／Selected色をDesign Token化する
- MayaのDark Themeと選択色に馴染み、警告色を通常Accentへ流用しない
- 技術契約名を通常UIへ露出せず、アーティストの作業語彙へ置き換える
- 空状態、失敗、再起動要求、処理中の文言に必ず次の行動を含める

## 受け入れ条件

- Slider Drag中にSettledを実行せず、Release後に1回だけ実行する
- Drag 1回がUndo 1回になり、値と生成結果が正しく復元される
- Guideを多階層GroupへDrag & Dropし、保存・再読込後も階層と順序が一致する
- GuideとScale Typeの対応を一覧だけで判別し、複数Assignを完了できる
- 旧Sceneを開いた直後のSettled MeshとStable Cell IDがBeta基準と一致する
- Auto PreviewはManual Override可能で、Settled結果を変更しない
- Curve既定値が現行Scalar形状とGolden一致する
- Keyboard操作、Focus、文字切れ、High-DPIをMaya 2026で確認する

## 開発順序

### 開発ブランチの進捗（2026-09-08）

- Slider集約、Guide選択同期、安全なGroup化、多階層、Collapse保存、
  Inline Rename、検索、表示／Node Lockを実装済み。
- Guide行にScale Type名・色・未割当を表示。直接Group所属によるリンクは
  `[Group]`、無効Typeは`[OFF]`を併記し、Type名も検索対象とする。
  複数Typeの色が異なる場合は通常文字色を使う。
- 保存形式とNative評価規則は既存の単一`guide_id`を維持。
  多階層Groupの祖先へリンク効果を拡張しない。
- Guide側Assign／解除、Scale Type側Jump／絞り込みを実装済み。
- 残件：一つのScale Typeを複数Guideへ割り当てる一括Assign。現行の
  単一guide_idでは表現できないため、Scene／Payload契約を変更せず保留する。
- 回帰チェック：Maya付属mayapyで`tools/check_guide_type_links.py`。
  実シーンは`tools/measure_maya_slider_drag.py --group-selection type-links`。
  製品パスは前者へ`--installed`を付けて確認する。`type-link-undo`では
  割当1回がUndo 1回でScene／UIとも復元する。
- Parameter Section再編を開始。現行`Global`の4 Sectionを正本とし、未参照だった
  旧Distribution／Orientation／Cells／Shapeタブ構築コードを削除した。
- `Global`の初期表示は主要Parameterだけとし、詳細項目はSceneへ保存しない
  「詳細パラメータを表示」で段階開示する。Labelをアーティスト向け日本語へ整理し、
  全項目のTooltipに既定値と影響Stageを表示する。
- 配置／向きの均し強度と表面追従リングは、前提条件が無効ならDisableし、
  Tooltipへ理由を表示する。回帰チェックはMaya付属mayapyで
  `tools/check_parameter_sections.py`、製品パスは`--installed`を付ける。
- 配置／向き／境界／形状ごとのSection Resetを実装。既存`ScaleSettings`の
  既定値を正本にし、変更がある場合だけSettledを1回実行する。Maya Undo／Redo後は
  Scale Typeだけでなく全Parameter UIをScene JSONへ同期する。
  `--group-selection parameter-reset-undo`でScene／UIの1回Undoを確認する。
- Maya 2026をQt 150% Scaleで起動し、主要Label／値／Resetに文字切れや重なりが
  ないことをScreenshotで確認した。Advancedトグルは`StrongFocus`を明示し、
  Harnessの`--ui-screenshot`でTab Focus Policyも検証する。Phase 5は完了。
- 2026-09-07の既存Outlinerプローブでは、更新前後ともロックRedoに
  `There are no more commands to redo`が発生。リンク表示とは独立した
  未解決事項として、次回UndoキューとScene初期ロック状態を調べる。
- Auto Preview Budgetは、目標鱗数と直近Interactive総時間を使い、60ms未満なら
  2倍、120ms超なら半分へ1段階だけ調整する。同一操作中は値を固定し、Settled完了後に
  次の操作用として反映する。Autoの選択値と理由を表示し、Manualでは選択値を直接編集できる。
  Settled Budget、Stable Cell ID、Scene Schemaは変更しない。
  Maya Qt回帰チェックは`tools/check_auto_preview_budget.py`、製品パスは`--installed`を付ける。
- Installed Maya 2026の`dragon.mb`／`bifrostScalesSettings4`で実評価し、Interactive
  602.9msから128→64を選択、操作中128固定、Settled 512不変、Interactive／Settled
  各1回を確認した。`--auto-budget-probe`で再現でき、Phase 6は完了。
- Root→Tipの幅カーブと側面カーブをShape Sectionへ追加。幅は左右対称倍率、側面は
  既存Curvatureの法線方向倍率として、Card／CellのInteractive／Settledへ共通適用する。
  Point追加・削除・Drag移動・Reset・X/Y数値編集・Copy／Pasteに対応した。
- Curve契約は最大16点、X=0..1、線形補間、幅Y=0.05..4、側面Y=-4..4、
  既定値`[(0,1),(1,1)]`。旧Sceneは追加field未保持のまま中立値へ復元し、Scene Schema 5と
  Payload Schema 10を維持する。Behavior Contractのみ`0.10.9-vector-surface-4`へ更新した。
- Native Goldenで旧payloadと中立Curveの頂点・面が完全一致し、編集Curveの幅・反り変化を確認。
  Maya 2026 Qt操作チェック、Native 2/2、Schema監査50/50、Python全回帰（既知のローカル
  module/構築済みPack依存2件を除外）を通過した。Installed Maya batchでは24枚・144点・
  120面を維持して実行counter 2→3、設定保存とCurve payloadを確認した。
- `dragon.mb`のInstalled UIをQt 150%でShape欄へスクロールして撮影し、Curve描画、Root／Tip、
  X/Y、追加・削除・Reset・Copy／Pasteに文字切れ・重なりがないことを確認。Phase 7は完了。

1. 現行UIの操作計測とWidget／Callback／評価経路の棚卸し
2. Slider要求集約とInteractive／Settled状態機械
3. Guide OutlinerのScene正本・階層・Rename・選択同期
4. Guide―Scale Type関係表示と一括Assign
5. Parameter Section再編と文言・Visual Token
6. Auto Preview Budget
7. 2軸Curve UIと旧Scene移行
8. アーティスト操作テスト、回帰、Installer更新

## 2026-09-08: Interior Sculpt初期実装（Phase 7の要件修正）

上記の倍率Curveだけでは要求未達。Phase 7の完了判定を取り下げ、以下を追加した。

- opt-inの`sculpt_surface`（`vector-surface/1`）をGlobal／Scale Typeへ追加。
  未設定なら従来の頂点・面を維持。Type未設定はGlobalを継承する。
- 外周／Growthリングは従来のまま、中心fanだけを四角形グリッドと接続三角形に置換。
  XYZ変位は外周内へクランプしないため張り出し可能。自己交差の自動補正は行わない。
- 編集用は32／64／128分割の正規化パッチ。横／縦の高さCurveとMaya標準Sculpt／Grab／Smoothを利用。
  出力は操作中4、確定時8分割（各4..32）。高密度データは保持し、出力解像度変更で破棄しない。
- Global「内側を立体編集…」、Scale Type「このTypeの内側を立体編集…」から開く。
  Curveを調整→「編集メッシュ作成 / カーブ反映」→Mayaで造形→「Systemへ適用」。
  保存先を切り替えた状態や編集パッチのトポロジー／外縁変更は適用を拒否する。
  パッチは閉じても削除しない。選択して「選択中の編集パッチを再開」で再利用できる。
- ブラシ中にSystemを再生成しない。明示的な適用だけで更新する。
  新しい面構造はCards選択時もCells生成を使用するため、従来Cardsより負荷が増える。
- 現段階は試作。正規化パッチは実際の鱗の輪郭そのものではないため、適用後の確認が必要。
  境界の自動Freeze、編集分割数の途中変更、適応分割、細部の自動LOD保持は未実装。
  Curve反映のMFnMesh操作はMaya Undo対象外（Sculptブラシ操作とSystem設定保存とは別）。
  極端な張り出し、低解像度で失われる細部、多数鱗での性能はアーティスト実測を残す。
- 検証: Python 169件（既知ローカル依存2件除外）、Native core、Schema 50/50。
  `tools/check_sculpt_editor_maya.py`を独立Maya GUIの初期化後に実行し、作成／XYZ／Curve／再開／境界拒否を確認。
  `tools/check_shape_curves_native_maya.py`はinstalled NativeのGlobal／Type／出力解像度／従来復帰も確認する。
  GUIテストは`BIFROST_SCALES_MAYA_INITIALIZED=1`。専用検証プロセスだけ
  `BIFROST_SCULPT_GUI_CHECK=1`で終了させる。ユーザー作業中Mayaでは指定しない。
  mayapy／mayabatchのQt検証はダイアログ生成で停止するため、合格扱いしない。
- 最終開発版は49ファイルを検証してインストール済み。Maya再起動が必要。
  復元先: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260908_203215_26cf1852`。
  実機NativeログにはMaya起動時の`NameError: xgg is not defined`（初回）、
  `menuSet: There are no menuSets to query`／`findMenuSetFromLabel`（最終batch）も残る。
  本機能の比較チェックはその後PASSしたが、起動エラー自体は未調査。
  証跡は`native/build/sculpt-native-maya-final.log`、`sculpt-editor-result.txt`、
  `sculpt-pytest.log`、`sculpt-build.log`（既存getenv警告あり）。

## 2026-09-08: 境界編集・再開の修正と全面編集v2

- 新規編集パッチは`vector-surface/2`。境界もXYZ変位を保存するため、初回適用前に
  ブラシが境界へ触れてもエラーにならない。UIを閉じても再開・適用できる。
- `resume`は接続構造だけを検証し、造形の検証で再接続を拒否しない。
  境界が動いた旧v1パッチも「選択中の編集パッチを再開」で開ける。
  「旧パッチを全面編集へ移行」で確認後、現存する頂点位置を保持してv2へ変換する。
  続けて「Systemへ適用」。移行で鱗への割当範囲が広がるため、出力の見た目は変わる。
- v2はGrowth値・内部リング分割数に依存せず、外周までの連続した四角形グリッドを出力する。
  Growth以外の既存輪郭調整は再利用。配置上のCell境界は保持し、造形上の境界は動かせる。
  全有効Typeがv2の場合、Growthと旧リング分割数をUIで無効化する。
- v1と未設定の旧出力は変更しない。新形式へ自動移行しない。
  Native Behavior Contractは`0.10.9-vector-surface-4`。
- 同一入力比較: 修正前Python10件／Native2件PASS、修正後Python170件
  （既知ローカル依存2件除外）／Native2件／Schema50件PASS。
  NativeでGrowth・分割数変更に対する頂点と面の完全一致、境界変位の反映、
  Growth以外の輪郭調整が効くこと、従来v1の外周・リング互換を確認。
- 独立Maya GUIで初回適用前の境界移動、UI再開、標準Sculpt/Grab/Smoothツール起動、
  境界変更済みv1の再開・移行と頂点位置保持を確認。ブラシ軌跡そのものは自動入力せず、
  頂点変位を同一入力で与える検証。実操作の感触はアーティスト確認を残す。
- 開発版49ファイルをバックアップ付きインストール済み。Maya再起動が必要。
  復元先: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260908_223745_931f4783`。
  証跡: `native/build/full-sculpt-pytest.log`、`full-sculpt-build.log`、
  `full-sculpt-native-maya.log`、`sculpt-editor-result.txt`。
  既存getenv警告、Maya起動時の環境依存エラーは機能修正の対象外。
- 残件: 正規化パッチと実際の鱗の見た目の一致、Curve反映操作のUndo対応、
  高周波形状の自動LOD保持。これらを完了扱いにしない。

## 2026-09-09: 外周固定v3・カーブUI廃止・内部厚み

v2の外周自由編集は要求の解釈違い。新規パッチを`vector-surface/3`へ変更した。

- v3出力は元のCell外周頂点（Gap・Lift・境界法線を含む）をそのまま保持する。
  Growthリングは出さず、内部グリッドを外周へ接続する。内部のXYZ張り出しは維持。
  編集パッチの境界にブラシが触れても適用を拒否しない。適用時は境界変位を無視し、
  Mayaパッチの境界のみUndo可能な操作で復元する。ブラシ中の一時的な境界移動はあり得る。
- v1/v2保存データは自動変更しない。既存パッチは選択→再開→「旧パッチを固定外周方式へ移行」
  →確認→Systemへ適用。内部形状を保持し、旧カーブの効果を変位へ取り込む。
  外周復元と割当範囲の変更により旧v2の出力形状は変わる。
- Globalと編集パッチのカーブUI、Scale TypeのWidth/Length UIを削除。
  旧カーブ・Width/Length保存値とNative評価は互換性のため維持し、他の設定編集で上書きしない。
  未使用の`shape_curve_editor.py`と専用UIチェックを削除。純粋な旧カーブ評価関数と互換テストは残す。
- Sizeは「形状の強さ」、Type Sizeは「形状の強さ倍率」へ変更。保存キー・数値の意味は維持。
  Global強度スライダーは0.001..1の対数範囲に絞り、数値入力の旧範囲は保持する。
- Global `normal_offset`（既定0）を追加。Type `offset`のリンク強度付き補正と加算し、
  Shape強度を基準に内部の法線方向へ適用。v3外周は厚み変更の影響を受けない。
  UIは内部厚み／内部厚み補正の%表示。旧offset 0.1は10%、UI 0.1%は保存値0.001。
  スライダーは±2%、数値入力は±400%、刻み0.01%。旧シーンの見た目を再解釈しない。
  Global厚みを使うと外周を保持できるCells評価を使用する（Cardsより重くなり得る）。
- 検証: Python171件（既知ローカル依存2件除外）、Native2件、Schema50/50。
  Nativeで旧外周との頂点完全一致、厚み変更時の外周不変、Growth/旧リング分割数非依存を確認。
  独立Maya GUIで境界復元・再開・旧パッチ移行、カーブ/Width/Length UI削除、
  Global/Type厚みの%往復と非表示旧値保持を確認するハーネスを更新。
  実ブラシ軌跡を自動入力したのではなく、同一の頂点変位と標準ツール起動で検証している。
  Installed Maya/Bifrostで旧形式/v2/v3とGlobal/Type厚みの評価・保存を確認。
- 開発版48ファイルを検証しインストール済み。Maya再起動が必要。
  バックアップ: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260909_000528_09ae25a7`。
  ログ: `native/build/pinned-sculpt-build.log`、`pinned-sculpt-pytest.log`、
  `pinned-sculpt-native-maya.log`、`sculpt-editor-result.txt`。
  既存getenv警告、batch起動時menuSet/findMenuSetFromLabelエラーは残るが機能チェックはPASS。
- 残件: 正規化編集パッチと実際の鱗の見た目の一致、細部を保持する自動LOD、
  実ブラシ操作の感触。製品全体のUIUX完了とは扱わない。

## 2026-09-09: 円盤編集パッチ・外周追従の三角形化

- v3の内部出力を三角形に変更。四角形の凹化・非平面四角形の曖昧な分割を除去する。
  正規化格子を滑らかな円盤へ配置し、外周の角度補間ではなくray/edge交点で対応位置を求める。
  投影中心は外周の平面上の重心を使用。各面の対角線は変形前の向きと面積で決め、
  Sculptのたびに接続が切り替わらないようにする。外周頂点とGapの固定は継続。
- 新規編集メッシュも半径0.5の円盤・三角形に変更。保存変位のn×n座標とXYZ値は維持し、
  円盤の基準位置との差分として保存・再読込する。編集配置は`bifrostSculptLayout=disk-triangles/1`。
  既存の属性なしパッチはsquare-quads/1として再開し、勝手に変形・再接続しない。
  円盤で再編集したい場合は、Systemへ保存後に新しい編集パッチを作る。
- v3は不具合修正として新しい配置と三角形を使用するため、内部頂点の基準位置と面数は変わる。
  保存済みのXYZ変位そのものは変更しない。v1/v2は従来の評価を維持。
  Native Behaviorは`0.10.9-vector-surface-4`。
- 非対称な外周で分割数4/5/8/16/31/32の三角形向き・非ゼロ面積・面積合計・辺接続・
  外周以外の穴がないことを自動検証。外周座標、厚み、Growth非依存、旧形式の回帰も維持。
  Python172件（既知ローカル依存2件除外）、Native2件、Schema50/50。
  Maya GUIで円盤描画・変位保存・再開・境界復元、旧四角形パッチの再開を確認。
  画像: `native/build/disk-sculpt-preview.png`。実ブラシ軌跡は自動入力していない。
- 過大なXYZスカルプトで意図的に面を裏返す／自己交差させる場合まで防ぐものではない。
  編集用円盤は正規化基準であり、各鱗固有の輪郭を完全再現する編集表示は残件。
- 開発版48ファイルを検証しインストール。
  バックアップ: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260909_031859_962e97f5`。
  証跡: `native/build/disk-sculpt-build.log`、`disk-sculpt-pytest.log`、
  `disk-sculpt-native-maya.log`、`sculpt-editor-result.txt`。

## 2026-09-09: 編集パッチの専用ビュー

- `sculpt_editor.py`にMaya標準standalone modelEditor・専用カメラを埋め込み。
  Sculpt / Grab / SmoothはMaya標準アイコンとコンテキストを再利用。
  ビューへ入った時だけブラシを有効化し、離れると元の選択・ツールへ戻す。
- System UUID + Type IDでドラフトを再開。初回は自動作成。
  追加操作はメニューへ移動。新規32/64/128分割は旧ドラフトを削除せず作成できる。
  通常ビューはネイティブitemFilterで現在のパッチだけ除外し、閉じると元のfilterに戻す。
  開いている間のパッチのリネーム／新規ビューパネルへの除外追従は未対応。
- 手動適用を維持。ブラシ操作中のSystem評価・ポーリングは追加していない。
  一時カメラはシーン保存対象外。カメラ・filter・選択切替はUndo対象外。
  閉じる／Escape／親UI終了／シーン切替時に専用リソースを解放する。
- `tools/check_sculpt_view_maya.py`を独立したMaya GUIにexecuteDeferredで実行。
  既存パッチ回帰に加え、描画・アイコン・ブラシ切替・Enter/Leave・適用・
  元カメラ/filter/選択/Undoの保持・再開・別Type分離・分割指定・シーン切替を検証。
  `BIFROST_SCULPT_CHECK_INSTALLED=1`ならソースをsys.pathへ追加せずインストール先を検証。
  実際のマウスによるブラシストロークの入力とMaya 2026以外での動作は未検証。
- Python172件（既知ローカル依存2件除外）、Schema50/50。
  証跡: `native/build/sculpt-view-result.txt`、`sculpt-view-pytest.log`、
  `sculpt-view-schema.log`、`sculpt-panel-render.png`。
  Qt widgetのgrab画像ではOpenGL領域が黒くなるため、描画判定にはpanelのplayblastを使用。

## 2026-09-09: ストローク後の自動適用（任意）

- 編集パッチ下部に「ストローク後に適用」を追加。既定OFFで従来の手動適用を維持。
  マウス／タブレットの解放から250ms待ち、連続操作をまとめる。
  専用ビュー内の左ストロークだけを対象とし、Altカメラ操作は対象外。
  押下中はキャプチャもSystemへの適用もしない。ポーリングやDG全体の監視は追加しない。
- キャプチャ結果が前回と同一ならSystemへ送らない。境界だけの変更は境界復元のみ。
  OFF／手動適用／ドラフト切替／解除／終了で予約を破棄。
  Undo/Redoでは自動適用をOFFにして、Undo結果への再適用を防ぐ。
  保存先変更・トポロジー不整合などのエラーもOFFにし、UI内に原因を表示する。
- Maya標準sculptMeshCacheCtxはafterStrokeCmdを持たないため、Qt入力の解放を利用。
  MayaのmakeStrokeで実際のブラシ変形を検証し、同一形状の手動適用との一致も検証。
  ペンタブレット実機の入力・筆圧については未検証。
- `tools/check_sculpt_auto_apply_maya.py`は既存専用ビューの回帰も実行する。
  操作中0回、連続ストローク1回、変更なし0回、Alt操作0回、手動との一致、
  Undo・エラー時停止、OFF・手動適用・終了時の予約取消をチェック。
  ソースとインストール先でPASS。Python172件（既知環境依存2件除外）、Schema50/50。
  Bifrost出力経路の旧形式／v2／固定外周／Global・Type厚みもPASS。
  mayabatch起動時の既存menuSet / findMenuSetFromLabel初期化エラーは残存。
  詳細ログは`native/build/sculpt-auto-native-maya.log`。
  形状キャプチャの中央値は32分割4ms／64分割16ms／128分割64ms程度。
  System再評価時間を含まない。重いSystemでは手動適用を使用する。
- 証跡: `native/build/sculpt-auto-result.json`、`sculpt-auto-before.log`、
  `sculpt-auto-installed.log`、`sculpt-auto-pytest.log`、`sculpt-auto-schema.log`。
  実行は独立Maya GUIのexecuteDeferredから行い、
  `BIFROST_SCULPT_CHECK_INSTALLED=1`でインストール先を検証する。

## 2026-09-09: Phase 8 — Guide表示・ロックのUndo/Redo回帰

- 旧Outlinerプローブでは`dragon.mb` / `bifrostScalesSettings4`のUndo/Redoは通過したが、
  起動時に別Systemのpreview接続欠落でErrorになった後、backendだけを
  指定Systemへ切り替えており、UI選択と表示状態が不一致だった。
  `measure_maya_slider_drag.py`を実UIのSystem選択経路へ変更し、UIログも結果に保存する。
  接続欠落の既存System自体は修復・削除しない。
  `native/build/guide-lock-ui-before.json`に旧プローブの生の結果を保持。
- 正しいUI選択経路へ変更した最初の測定では、大型既存シーンでUndo直後に存在したRedoが
  イベント処理後に消え、`undo_after_settled=selectionMaskResetAll`を観測した。
  原因は製品のUI同期ではなく、検証本体がSceneOpenedと同じdeferred callback内で開始され、
  Maya標準のSceneOpened後処理より先に操作していたこと。
  起動ハーネスを「scene open → callback終了 → lowest-priority idleで測定」の二段階へ変更。
  これによりMaya標準初期化を先に完了させ、実ユーザー操作と同じ順序で測定する。
  診断ログ: `guide-lock-ui-diagnose.json`、`guide-lock-ui-idle-settled.json`、
  `guide-lock-ui-startup-settled.json`（すべて`native/build`内）。
- 別条件として、Undo後に現在と同じ表示／ロック状態を再指定すると、
  Mayaの不要な書込みによってRedo履歴が消失することを新規の独立GUI fixtureで再現。
  Guide/Group × 表示/ロック × 初期ON/OFFの8条件すべてが修正前FAIL。
- `scene.py`の共通setterで所有権検証後に現在値と比較し、変更なしなら書込み・Undo chunkを省略。
  通常の状態変更、所有権エラー、設定JSON、Guide評価fingerprintは従来通り。
  Query失敗は既定値扱いで黙って省略せず、呼出元へエラーを返す。
- `tools/check_guide_presentation_undo_maya.py`で実Qtチェック操作、Undo/Redo後のScene/UI一致、
  1操作1Undo、同値再指定によるRedo保持、形状更新要求0回を自動検証。
  `BIFROST_GUIDE_CHECK_INSTALLED=1`でインストール先を確認。
  `BIFROST_GUIDE_CHECK_REPORT`で`native/build`配下の結果ファイル名を指定。
  MayaのexecuteDeferredから独立GUIで実行し、実ユーザーの開いているシーンには接続しない。
- 同一8条件が修正後PASS。Python173件（既知環境依存2件除外）。
  Schema50/50。インストール先も8/8、形状更新要求0回。
  二段階起動後の`dragon.mb`でもソース／インストール先ともUndo/RedoのScene/UI同期、
  Redo保持、生成評価0回、実行counter不変を確認。Phase 8のRedo残件は解消。
  証跡: `native/build/guide-presentation-before.json`、`guide-presentation-after.json`、
  `guide-presentation-installed.json`、`guide-presentation-pytest.log`、
  `guide-lock-ui-two-stage-source.json`、`guide-lock-ui-two-stage-installed.json`。
  製品版全体の受入れ完了ではなく、Phase 8の回帰ケースを一つ固定した段階。

## 2026-09-09: スカルプト専用ビューのmodelPanel Syntax Error修正

- 原因はMaya標準`modelPanel`を非表示の`cmds.window`に作成した後、Qt側へ再親子付けしていたこと。
  カーソル出入り時のツール切替でRenderer UI更新が走ると、Mayaが
  `||modelPanel5|modelPanel5|modelPanel5`のような不正UIパスを生成していた。
- 専用ビューをバーなしのstandalone `modelEditor`へ置換。既存のMaya標準Viewport、
  Sculpt / Grab / Smooth、専用カメラ、通常ビュー除外、Enter/Leave時のツール復元は維持。
  専用ビューの対象限定は`itemFilter`で行い、終了時にeditorとfilterを解放する。
- `tools/check_sculpt_view_maya.py`でScript Editor履歴を毎回新規取得し、
  Enter/Leave前後の`updateRendererUI`と終了時に`updateModelPanelBar ||`、
  `cleanupModelPanelBar ||`、Syntax Errorが出ないことを回帰化。
- 修正前は同じ独立Maya GUIで`cleanupModelPanelBar ||...`を再現。修正後は専用ビュー、
  描画、3ブラシ、選択・ツール・Undo・カメラ・通常ビューfilter復元、再開、シーン切替がPASS。
  自動適用統合もPASS（32/64/128分割のcapture中央値4.19/15.92/63.17ms）。
  Python回帰173件（既知環境依存2件除外）、Schema50/50。
  証跡: `native/build/sculpt-view-result.txt`、`sculpt-view-script-editor.log`、
  `sculpt-panel-render.png`、`sculpt-auto-result.json`、`sculpt-model-editor-auto.log`。
  開発版48ファイルを検証してインストールし、インストール先だけを読む同じGUI回帰もPASS。
  バックアップ: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260909_220144_af4317f0`。
  Maya 2026以外とペンタブレット実機入力は未検証。

## 2026-09-10: Phase 8 — Interior Sculpt実製品経路とUndo統合

- `tools/check_sculpt_auto_apply_maya.py`を、編集パッチ単体だけでなく実UIから新規Native Systemを作り、
  Global／Scale Typeの編集画面をButtonで開いて適用する製品経路まで拡張。
- 修正前はGlobalの「適用」が設定保存の`Bifrost Scales Interior Sculpt`と、
  Settled評価の`Bifrost Scales Parameter Edit`の2 Undoに分裂し、新規回帰がFAILした。
  `_parameter_changed(..., settle=True)`を既存のInterior Sculpt chunk内へ移し、
  設定、境界復元、Native Graph更新を1回のUndo/Redoで復元する。
- System作成後のUI再読込が、既に生成済みの同じ設定をもう一度Settled評価していた。
  設定読込時はdelay値の同期だけを行い、評価要求を出さないように変更。
  同一操作のSettled完了通知は修正前3回、修正後はGlobal／Type適用の2回のみ。
- Installed Maya 2026で24枚、通常744頂点→Global Sculpt 2,184頂点を確認。
  Undo 1回で設定・UI・744頂点へ戻り、Redo 1回で設定・UI・2,184頂点へ復元。
  Type Sculpt適用、標準3ブラシ、任意自動適用、Syntax Error不在も同じ実行でPASS。
- Python回帰173件（既知環境依存2件除外）、Schema50/50。
  開発版48ファイルを検証してインストール済み。
  バックアップ: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260910_012512_89ca99ac`。
  証跡: `native/build/sculpt-auto-result.json`、`sculpt-product-output.log`、
  `sculpt-view-script-editor.log`、`sculpt-product-schema.json`。

## 2026-09-10: 新規Maya起動時のNative Backend自動初期化

- `-noAutoloadPlugins`相当の新規Mayaでは、System作成前のreadiness判定が
  `bifrostGraph` / `vnn`コマンド不在を即時エラーにしていた。
- 全System作成・Target再設定が通る共通Backendのreadiness境界で、
  必要な場合だけMaya標準`bifrostGraph`プラグインをロードしてから再判定する。
  ロード自体が失敗した場合は原因を保持した明示的なエラーにする。
- 同一のInstalled Maya 2026 GUIテストは修正前に報告と同じ2理由でFAILし、
  修正後は`plugin_loaded_before=false`、`plugin_loaded_after=true`でPASS。
  24枚、744→2,184頂点、Global／Type Sculpt、Undo/Redo、Settled評価2回も維持。
- Python回帰174件（既知環境依存2件除外）、Schema 50/50。
  開発版48ファイルを検証してインストール済み。
  バックアップ: `C:\Users\takum\Documents\maya\modules\_BifrostScales_backup_20260910_153057_aa3fea95`。
  証跡: `native/build/sculpt-auto-result.json`、
  `native/build/schema-contract-plugin-autoload.json`。

## 2026-09-10: スカルプト専用ビューの描画対象固定

- 名前のitemFilterだけではVP2の描画対象を限定できず、重なるシーンメッシュが専用ビューに映っていた。
  bind_viewで専用modelEditorのviewSelectedとsetSelectedを設定し、対象パッチをビュー固有の集合に固定。
  シーン全体のvisibilityや通常ビューのIsolate Selectは変更しない。
- 同じ重なりシーンで、確認用メッシュの表示ON/OFFによる専用ビュー画像差を修正前に再現。
  修正後は専用ビュー画像が完全一致し、通常ビュー画像は表示ON/OFFで変化することを確認。
  再開・新規パッチ作成後も集合のメンバーが編集対象1枚だけであることを検証。
- Installed Maya 2026の既存統合テストもPASS。
  3ブラシ、Global/Type適用、Undo/Redo、24枚744→2,184頂点、Settled評価2回を維持。
  証跡: native/build/sculpt-isolation-True.png、sculpt-isolation-False.png、
  sculpt-scene-True.png、sculpt-scene-False.png、sculpt-auto-result.json。
  インストール時バックアップ: _BifrostScales_backup_20260910_170100_9ffb4f72。

## 2026-09-10: 内部スカルプトの外周越えをセル寸法に合わせる

- vector-surface/3の中立形状はセル外周へ写像していたが、平面変位だけはshape.size
  （既定0.1）倍で加算していた。外周へ直接クランプしているのではなく、
  編集パッチ上の張り出しが出力で縮小されて内側に留まっていた。
- 固定外周方式の平面変位を、編集後の座標から同じセル写像で計算する。
  半径は1に制限せず外側へ外挿する。外周の固定、面構成、法線方向変位、
  無編集状態と旧vector-surface/1・2は維持する。
  保存済みvector-surface/3の平面変位もセル寸法に合わせて反映されるため、
  以前の縮小された見た目とは意図的に異なる。
- Native回帰: 半径0.5の編集ディスク中心を横0.75へ動かす入力で、
  修正前FAIL、修正後セル外周越えPASS。Global/Type一致、固定外周と同一面構成を確認。
  Native 2/2、Python174件（既知環境依存2件除外）、Schema50/50。
- Behavior契約は0.10.9-vector-surface-5。Nativeを再ビルド・インストールし、
  Installed Maya 2026でGlobal横0.75／Type縦0.75の適用、Undo/Redo、
  専用ビューの独立表示を含むGUI統合PASS。
  バックアップ: _BifrostScales_backup_20260910_183856_a1d3a3b4。
  証跡: native/build/sculpt-overhang-before.log、sculpt-overhang-after.log、
  sculpt-overhang-pack.log、overhang-schema.json、sculpt-auto-result.json。
  ビルドスクリプトが更新したローカルmodは、事前SHA256と完全一致する内容へ復元済み。

## 2026-09-10: スカルプト高さのセル寸法換算

- 前回残した高さ変位はshape.size倍で、さらにcell_safeによる
  local_spacing×0.92の上限を受けていた。UIの形状の強さ1でも高さが抑制される。
- 固定外周vector-surface/3の高さは、接平面上のセル幅・長さの幾何平均と、
  上限適用前の形状の強さ（Guide/Type倍率・ばらつき込み）で換算する。
  セル間隔上限はスカルプト高さに適用しない。厚みオフセット、
  既存の平面変位、外周、面構成、旧schemaの処理は維持。
  保存済みv3スカルプトの高さも新しい換算で変わる。
- Native同一入力で修正前FAIL、修正後PASS。セル幅・長さ2、パッチ高さ0.2で、
  強さ1→高さ0.4、強さ2→0.8。負方向、セル寸法2倍、Global/Type一致、
  外周固定と面構成不変も検証。Native2/2、Python174件（既知2件除外）、Schema50/50。
- Behaviorは0.10.9-vector-surface-6。48ファイルを検証してインストール。
  バックアップ: _BifrostScales_backup_20260910_234609_88626c9c。
  証跡: native/build/sculpt-height-before.log、sculpt-height-after.log、
  sculpt-height-pack.log、sculpt-height-schema.json、sculpt-auto-result.json。

## 2026-09-13: スカルプトパッチの前方表示

- 編集パッチの+V方向を示す黄色い3D矢印を専用modelEditorへ追加。
  カメラを回してもパッチ座標に追従し、説明文にも「前方（+V）」を表示する。
- マーカーは専用ビューの表示集合にだけ含め、通常modelPanelのフィルターでは除外。
  Mayaシーンへ保存せず、ウィンドウ終了時に削除する。
- ソース版とInstalled Maya 2026で、矢印の描画有無による画像差、
  通常ビュー非表示、パッチ再開・新規作成、終了時解放を確認。
  既存の表示隔離、3ブラシ、Global/Type適用、Undo/Redo統合もPASS。
  バックアップ: _BifrostScales_backup_20260913_001145_1b918785。
  証跡: native/build/sculpt-direction-True.png、
  sculpt-direction-False.png、sculpt-view-result.txt、sculpt-auto-result.json。

## 2026-09-13: Phase 8 — 保存再読込とInstallerライフサイクル

- Installed Maya 2026の実UIで、System作成→Global Sculpt→Undo/Redo→
  Scale Type Sculpt→mayaBinary保存→新規Scene→再読込を一続きで検証。
  24枚、744→2,184頂点、設定JSON、Global/Typeの編集ドラフトを維持する。
  専用カメラと前方マーカーは保存されず、再読込後の編集画面は既存ドラフトを再開する。
- `tools/check_sculpt_auto_apply_maya.py`へ上記受入を追加。
  Settled評価はGlobal/Type適用の2回だけで、Scene再読込による重複評価はない。
  証跡: `native/build/sculpt-product-roundtrip.mb`、`sculpt-auto-result.json`。
- 現行48ファイルからPhase 8開発用One-click ZIPを2回生成し、
  SHA-256完全一致を確認。隔離Maya modulesで新規導入、同版更新Backup、
  復旧可能なアンインストール、二重アンインストールをPASS。
  Bundle: `native/build/BifrostScales_0_10_9_UIUX_Phase8_20260913_185346-A.zip`
  SHA-256: `ba108118aaf3556fff7539ab2ed5357d4be0bdc69bbbe46baed28cdcef5f5fe6`
  既存Public Beta ZIPは更新していない。
- Python174件（既知環境依存2件除外）、Native 2/2、Schema 50/50。
  Phase 8の保存再読込・Installer受入は固定したが、製品版リリース判定全体は未完了。

## 2026-09-13: Phase 8 — P0 1〜4統合回帰と再現Build

- Installed Maya 2026で`dragon.mb` / `bifrostScalesSettings4`を別Processから2回評価。
  14,221枚、867,481頂点、853,260面、初期／編集後Payloadが完全一致し、
  Interactive／Settled各1回、Undo後の初期Payload復元を確認した。
- `--stable-id-probe`を`tools/measure_maya_slider_drag.py`へ追加。
  全14,221 Cell IDは重複0、2回のID列SHA-256は
  `2a2074176f35606eb532bc3e7552207ce64d31ebae374a6701a6641c5f125bce`で一致した。
  2回のMain Thread停止はInteractive 109〜110 ms、Settled 156〜157 ms。
- 旧ログの14,444枚はScene保存済みGraphを再評価する前の値だった。現在のSceneは20 Guide、
  X対称展開後37 Guide、5 Scale Typeで、09-08以降の実評価基準14,221枚と一致する。
- MSVC Linkへ`/Brepro`を追加。`tools/check_native_build_reproducibility.py`でClean buildを
  2回行い、Packの配布対象13ファイルが全SHA-256一致することを確認した。
  Source／Installed DLLは共に
  `b82b8462f8c90c0076e78da118bd051d7d55e6fb1438e14f09e7e860c71fc2cf`。
- 新PackからOne-click ZIPを2回生成し、48ファイル、1,655,232 bytes、SHA-256
  `57645a2f5262689a545fd14077a93074145db34d5cb0ee2e3a5c087fcf0c4070`で一致。
  隔離`maya/modules`で新規導入、同版更新Backup、回復可能Uninstall、二重UninstallをPASS。
- Qt 150%のInstalled UIでShape欄を撮影し、Keyboard Focus、表示中の評価0回を確認。
  Python 174件（既知環境依存2件除外）、Native 2/2、Schema 50/50をPASS。
  公開Beta ZIPとVersionは変更していない。P0 1〜4の証跡固定までで、Release判定は未実施。

## 2026-09-17: Release UI整理（進行中）

- Main UIに日本語/English切替を追加。Qt設定へ保存し、System/Guide/Type名、
  ComboBoxの保存値、パラメータは翻訳対象外。基本ラベルとSculpt操作を対応。
  動的メッセージ・全Tooltipの翻訳網羅は未完了。
- Float sliderは数値入力でsoft rangeを拡張。Global反り、前後位置、Global/Type厚みは
  保存側も従来範囲を超えられる。角度・割合の意味上の制限は維持。
  Type倍率やNative内部で制限する他パラメータの拡張は残作業。
- Settled budgetはSettings構築時に自動算出し、旧手動値は無視する。
  Native ABI用フィールドは残す。最大50,000候補／推定2,000,000頂点の保守的上限。
  実メモリ測定ではない。上限適用時だけUI警告。通常設定では出さない。
- Growth、旧内側リング分割の編集欄、Sculpt旧パッチ移行操作を削除。
  既存Sceneの見た目保持用の読み込みとNative互換経路はまだ残る。
  Diagnosticsから旧ツール検索を除去、legacy_cleanup.pyを配布対象外にした。
- 旧0.10.8生成物2ファイル（408,946 bytes）を削除。復旧ZIP:
  `native/build/retired-artifacts-20260917-023808-0a589488.zip`。
  `tools/cleanup_retired_artifacts.py`は固定allowlist、hash検証、再実行可能。
  制作Scene、incrementalSave、ローカルmod、公開Betaは保持。
- Python176件（既知環境依存2件除外）、Maya Qt release UIチェックPASS。
  `tools/check_release_settings_maya.py`の同一fixture比較で通常24枚/144頂点/120面と
  payload hashを維持。旧8枚capは24枚へ修正、拡張値のNative payload到達を確認。
  証跡: `native/build/release-settings-before.json` と `release-settings-source.json`。
  Source Python検証はテストプロセス内のみNativeのmodule rootを実際のInstalled Packへ向ける。
  単体MayaのmenuSet/Cg/Amino終了時警告あり、比較自体は成功。
- 最初のインストールは起動中Maya検出で安全停止。Maya終了を確認後に再実行し成功。
  Backup: `_BifrostScales_backup_20260917_024345_1e8774c6`、48ファイル検証済み。
  Installed Qt/native同一入力比較PASS、47 runtime filesがSourceとSHA-256一致。
  成功証跡: `native/build/release-settings-after.json` と `release-settings-after.log`。
  初回install失敗後に走ったafter比較は旧capを検出して失敗。最終ログは更新成功後の再検証結果。
- 残作業: 翻訳網羅、残りの数値入力制限、旧Native生成経路の整理、旧生成物の追加棚卸し、
  ストローク軌跡の実GUI確認。

## 2026-09-17: Guide checkbox操作とSculpt中心の形状UI整理

- V/Lがマウスで切り替わらない原因は、`_GuideTreeWidget.edit`が名前以外の列で
  Qt delegateのcheckbox eventまで遮断していたこと。名前欄だけtext editorを許可する
  delegateへ置換。マウスイベント試験は変更前FAIL、変更後4/4 PASS。
- V/LをVisible/Lock（日本語: 表示/ロック）へ変更。表示はGuideだけの表示切替、
  ロックはノードの削除/リネーム/親変更防止であり、鱗の生成有効/無効ではない。
- Global詳細Shapeのlift/inset/squash/expand/tip_roundness/tip_offset/forward_offsetと
  Typeのtip_offsetをUIから削除。保存済みの値は保持し、UI更新で既存形状を変えない。
  Global/Type curvature、normal_offset、size、random_size、Type random_offsetは
  現行Sculptにも作用するため維持。Native生成アルゴリズムの変更はない。
- Maya GUI隔離fixtureでGuide/Group×表示/ロック×初期On/Offの8ケースを実クリックし、
  Maya状態、Undo/Redo、同値操作のRedo保持、再生成0回、非既定Shape保存値保持を確認。
  `native/build/guide-checkbox-gui-result-2.json`: PASS。
  単体mayapy+Qtの併用検証はホスト終了異常となったため、GUI fixtureへ切替。
  最初のGUI実行で既存maintenance iconのQProxyStyle wrapperエラーを検出し、
  style参照不要な歯車表示へ変更して再検証PASS。
- Python176件（既知環境依存2件除外）、Qt UI/クリック試験PASS。
  48ファイルをインストール、47 runtime filesがSourceとhash一致。
  Backup: `_BifrostScales_backup_20260917_040630_942360af`。
  Installed Maya GUIでも同じ8ケースPASS、shape_requests=0。
  証跡: `native/build/guide-checkbox-installed-result.json`。

## 2026-09-17: 実メッシュ出力とStudio UI

- `Create Mesh / 実メッシュを作成`を追加。現在のgraph.out_meshをMaya標準の
  bifrostGeoToMayaで変換し、評価済みメッシュを独立コピーする。元System/Graphは保持し、
  1回のUndo/Redoに対応。Preview更新中は完了待ちを案内する。
  現在表示中の出力をコピーするため、自動Preview上限を超えた全量生成ではない。
  生成メッシュは標準マテリアル。元のBifrost表示と重なるため、確認時は表示を切り替える。
- ダークスレート＋ミントの配色、カード、2列パラメータ配置、簡潔なヘッダー、
  対象メッシュ操作メニュー、常設出力ボタンへ整理。Sculpt Editorも同じテーマ。
  Maya全体のスタイルは変更しない。追加依存なし。
- `tools/check_mesh_export_maya.py`を追加。移動したTargetとSculpt入力で、
  Source/Installedとも2184頂点・4080面、Graph payload/接続の不変、ワールド座標、
  Undo/Redo、System削除後も同じ独立形状が残ることを確認。
  初回検証は終了処理でMayaが異常終了したため、検証用MFn参照とUndoを破棄してから
  standaloneを終了するよう修正。再実行はexit 0。headless起動時menuSet警告は残る。
- Python回帰176件PASS、既知の保護対象mod/ビルド済みPack依存2件を除外。
  旧Createボタン文言に依存する2検査は新表記へ更新後PASS。
  Installed Qt UI/実クリック4ケースPASS。
- 49ファイルをインストール。Backup: `_BifrostScales_backup_20260917_050824_d3370972`。
  48 runtime filesがSourceとhash一致。Installed Maya GUIでも表示/ロック8ケース、
  Undo/Redo、shape_requests=0を確認（`native/build/studio-guide-installed-result.json`）。
  UI画像: `native/build/studio-ui.png`, `studio-ui-ja.png`（隔離Qt fixture）。
  実メッシュ証跡: `native/build/mesh-export-source.log`, `mesh-export-installed.log`。
  保護対象dragon.mb/local modのSHA256とincrementalSave 26ファイルは変更なし。

## 2026-09-17: Desktop UI修正（カード案を撤回）

- ユーザー指摘により前項のカード／ミント案は不採用。無彩色のダーク背景と
  赤寄りオレンジの操作点へ置換。角丸カード・2列配置・大型ヘッダーを撤去し、
  区切り線付き縦一列、揃ったラベル／数値欄、760px幅のマウス操作向け配置へ変更。
- タブを連続した矩形＋内容枠に戻し、配置・形状／ガイド編集／鱗タイプ／表示・更新へ改名。
  6種類のSVG線画アイコンを同梱。タブ、Sculpt、実メッシュ化などは文字ラベルを維持。
  設定・保存形式・生成アルゴリズムは変更なし。Mayaのアプリ全体には適用しない。
- 同一Qt fixtureの変更前後で、翻訳切替時の設定保持、数値入力、ガイドcheckbox4件PASS。
  SVG描画チェックを追加。日本語4タブを画像確認し、Type scroll背景の白抜けも修正。
  初回のQt findChildren(tuple)エラーは型別検索へ修正後PASS。
  Python176件PASS（既知環境依存2件除外）。
- ユーザーが保存・Maya終了後に55ファイルをインストール。Installed Qt試験PASS。
  54 runtime filesのhash一致。Installed Maya GUIで表示/ロック8ケース、Undo/Redo、
  shape_requests=0を確認（`native/build/desktop-guide-installed-result.json`）。
  Backup: `_BifrostScales_backup_20260917_052755_02c00fb4`。
  UI比較: `native/build/desktop-before-ja.png`, `desktop-after-ja.png`。
  各タブ: `desktop-after-ja-tab1.png`～`desktop-after-ja-tab3.png`。

## 2026-09-17: アウトライン撤去、UV、独立Quad Card出力

- 枠線を撤去し、キーボードフォーカスは背景色で表示。ComboBox右端の下向き三角SVGを追加。
  操作中表示の選択UIを削除し、UI snapshotはAuto固定。保存形式の既存enumは互換性のため維持。
- UV欠落の原因はNative operatorのinclude_uvs=falseとStatic GraphのUV接続なし。
  UVを出力し、Autodesk標準Geometry::Mesh::set_mesh_UVsでメッシュへ設定。
  参考: https://help.autodesk.com/cloudhelp/2024/ENU/Bifrost-Common/files/reference/bif/Bifrost_Common_reference_bif_set_mesh_UVs_html.html
  各鱗のrest面を局所2軸へ投影し、各軸の最小0／最大1へ正規化。
  各枚は同一0–1領域へ重ねる（ユーザー確認済み）。Sculpt張り出し・高さでUVを再投影しない。
- 独立機能「Cardメッシュを作成」を追加。既存Cell配置・向き・マスクの結果から、
  Cell局所境界を囲む平面Quadを1枚ずつ出力する。曲面への細分割やSculpt変形は適用しない。
  UVは各Quadの四隅0,0／0,1／1,1／1,0。鱗SystemのGraph/payload/接続は変更せず、
  一時Graphコピーで生成して実メッシュ化し、一時ノードを除去する。Undo/Redo対応。
  Card枚数は現在の鱗プレビューのSettled予算に従う（全量生成への拡張はしていない）。
- Host contractは`bifrost-scales/native-graph/4-dgmesh-2-uv`。
  既知の旧`4-dgmesh-1`だけをSystem選択時に1回更新。新Graphの評価成功まで旧Graphを保持し、
  失敗時は参照とSystem IDを復旧。パラメータ更新時のVNN編集は追加していない。
- 検証: Python176件PASS（保護local mod／ビルド済みPack依存2件除外）、Native 2 suite PASS。
  Coreに通常Cell／Sculpt／Quad各枚の0–1範囲・UV数・Quad topologyチェックを追加。
  Installed Mayaで旧UVなし配線再現→移行、移行失敗時の復旧、全face UV割当、
  各枚のUV shell数と範囲、Cardの4頂点1面、元Graph接続不変、Undo/Redo、独立性PASS。
  同一Sculpt fixtureの変更前後で2184頂点4080面の座標・topologyが完全一致。
  最初の旧版UV失敗時はstandalone終了が異常終了したため、失敗ログ出力と参照破棄を追加。
  移行fixtureの非対応deleteNode flagは不要だったため削除。最終検証exit 0。
  Maya headlessのmenuSet/OpenGL警告は残る（ログへ保存）。
- 56ファイルをインストール。Backup: `_BifrostScales_backup_20260917_061909_ecea5eee`。
  55 runtime filesがSourceとhash一致。Installed Maya GUIの表示/ロック8ケースと
  Undo/Redo、shape_requests=0もPASS（`native/build/uv-guide-installed-result.json`）。
  Installed Qt UI／Guide実クリック4件PASS。UI: `native/build/outline-free-ja.png`。
  証跡: `uv-installed.log`, `uv-card-native-tests.log`, `uv-tests.log`,
  `uv-geometry-baseline.json`（すべてnative/build）。
  dragon.mb/local mod SHA256とincrementalSave 26ファイルは変更なし。

## 2026-09-17: UV左右反転・Curve前後方向・Card撤去・影

- UVのUを反転。頂点座標／face winding／0–1範囲は維持。Cell/Sculptと操作中の簡易形状へ適用。
  同一Maya fixtureのface UV符号テストは旧版FAIL（Mirrored UV face）、修正版PASS。
  ガイドなしSculpt fixtureの2184頂点4080面は以前の座標・topologyと完全一致。
- Curve方向の鱗への寄与のみ180度反転（DirectionCurve/FlowCurve共通）。
  partition_tangent（Cell境界）、密度、ストローク点順、Point Guideは変更しない。
  保存済みCurveも新しい向きで評価される、意図した仕様変更。
  Native試験で正順／逆順Curve、Flow、境界方向不変、Point従来挙動を確認。
- 独立Card機能は不採用。Create Cards UI／backend分岐／quad_cards Native enumと専用生成を削除。
  作成済み実メッシュは削除しない。Autoの操作中用簡易形状は維持。
- Global/Typeボタンを「鱗をスカルプト / Sculpt Scales」に統一しアクセント色を適用。
  Qt標準の弱いdrop shadowを設定パネルと独立ボタンへ付与。
  影は親子で重複させず、生成処理・Maya全体スタイルへは影響させない。
- Python176件PASS（既知環境依存2件除外）、Native 2 suite PASS。
  Installed MayaのUV符号・各枚0–1 UV・旧graph更新・Undo/Redo・独立性PASS。
  Installed Qtの翻訳／ボタン撤去／数値入力／Guideクリック4件PASS。
  Headless起動時menuSet警告は既存のまま。ログ: `native/build/mirror-after.log`。
- 56ファイルをインストール。Backup: `_BifrostScales_backup_20260917_070231_d6bafb0f`。
  55 runtime filesのhash一致。Installed Maya GUIの表示/ロック8ケース、Undo/Redo、
  shape_requests=0もPASS（`native/build/mirror-guide-installed-result.json`）。
  UI画像: `native/build/shadow-ui-ja.png`。dragon.mb/local modのhashとincrementalSave 26件は不変。

## 新規スレッド開始時の指示

`D:\TA-Tools\MayaScales`の`main`からUI/UX専用ブランチを作成し、この文書、`BUILD_INFO.json`、`docs/ROADMAP_JA.md`、`docs/ARCHITECTURE_JA.md`を先に読んでください。最初の実装はSlider操作の評価回数とMain Thread停止時間を測る再現テストから始め、見た目の変更を先行させないでください。`dragon.mb`、`incrementalSave/`、ローカル`BifrostScales.mod`は保護対象です。
