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
- ZIP SHA-256: `0d75b843ba394e744f60213e77a6ed603750446be4c3cfd3eb6b42a22bc8089a`
- Native DLL SHA-256: `c9714eb6fd97a6448f8f4aecaf58f4f4285d5e1dbad7f4d223d46a1a463155fe`
- Native CTest `2 / 2`、Python `153`件、Schema `50 / 50`、Native-only `12 / 12`、Picker `18 / 18`、Release `16 / 16`を通過
- Public Bundleで新規導入、更新Backup、復旧可能なアンインストール、二重アンインストール、再導入を検証済み
- Maya 2026で`bifrostGraph`を明示ロードし、実ユーザーmodulesから`ready=True`と全Native契約を確認済み

Python全体テストの件数には、配布用Packを構築済みのソースツリーでは成立しない「Pack未構築」テストと、保護対象のローカル`BifrostScales.mod`を正規配布Moduleと仮定するテストを含めません。製品不具合ではなく開発PC固有の2件です。

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

1. 現行UIの操作計測とWidget／Callback／評価経路の棚卸し
2. Slider要求集約とInteractive／Settled状態機械
3. Guide OutlinerのScene正本・階層・Rename・選択同期
4. Guide―Scale Type関係表示と一括Assign
5. Parameter Section再編と文言・Visual Token
6. Auto Preview Budget
7. 2軸Curve UIと旧Scene移行
8. アーティスト操作テスト、回帰、Installer更新

## 新規スレッド開始時の指示

`D:\TA-Tools\MayaScales`の`main`からUI/UX専用ブランチを作成し、この文書、`BUILD_INFO.json`、`docs/ROADMAP_JA.md`、`docs/ARCHITECTURE_JA.md`を先に読んでください。最初の実装はSlider操作の評価回数とMain Thread停止時間を測る再現テストから始め、見た目の変更を先行させないでください。`dragon.mb`、`incrementalSave/`、ローカル`BifrostScales.mod`は保護対象です。
