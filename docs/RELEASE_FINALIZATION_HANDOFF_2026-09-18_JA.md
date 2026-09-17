# Bifrost Scales — リリース最終調整への引き継ぎ

更新日: 2026-09-18。**新規チャットでは最初にこの文書を読むこと。**
過去のUI/UX引き継ぎは経緯資料であり、撤回済みの案も含む。本書を現在の仕様として優先する。

## 1. 次回の目的と開始指示

ユーザーは現行機能と最新UIを確認・了承済み。次回はリリースに向けた最終調整。
UIの再設計や新機能追加を始めず、残る製品化ゲートを確認し、小さな修正と検証を進める。
Ponytail方針（既存機能・標準機能優先、依存追加や過剰な抽象化をしない）を継続する。

新規チャットへ渡す指示:

> このプロジェクトの `docs/RELEASE_FINALIZATION_HANDOFF_2026-09-18_JA.md` を読み、Git状態と保護対象を確認して、リリース最終調整を再開してください。採用済みUI・スカルプト・UV仕様を維持し、クリーンビルド、インストーラー、実機回帰、文書整合を優先してください。まだ正式リリース済みとは扱わないでください。

## 2. Git・バージョン・実行環境

- リポジトリ: `D:\TA-Tools\MayaScales`
- origin: `https://github.com/Takumi-cre3d/BifrostScales.git`
- 開発元: `codex/ui-ux-product`、マージ先: `main`。
- 開発のベース: `1a29a1cf87a49666a432b8c90285fc0c2c5c87ae`（0.10.9 Public Beta）。
- 実装確定コミット: `e0f277cd4f02d633e5a53f2c8802fe3e92c1ed0e`
  `Prepare product UI, sculpt workflow and UV mesh export`（66ファイル）。
- 本書と入口文書の更新は、その後の文書コミットとしてまとめる。
  現在のmain先端・リモート反映状況は `git log -3 --oneline --decorate` と `git status -sb` で確認する。
- コード上の版は引き続き **0.10.9**。正式版の番号・タグ・公開日は未決定。今回のマージはリリース公開ではない。
- 実機: Windows / Maya 2026.3.2、Bifrost 2.15。Maya 2025など他版の製品保証は未検証。
- インストール先: `C:\Users\takum\Documents\maya\modules\BifrostScales`
- 最終更新backup: `_BifrostScales_backup_20260917_070231_d6bafb0f`
- Native DLL SHA256: `799B552170C5A71FCFC67746246983AA7633C0379430C296B3AF635C9975337C`
- Runtime 55ファイルがsourceとinstalledでhash一致、moduleを含むインストール検証56ファイル。

## 3. 絶対に巻き込まないローカル資産

以下はコミット対象外。作業ツリーに残るのが正常であり、clean/resetで消さない。

| 対象 | 保護状態 |
|---|---|
| `dragon.mb` | SHA256 `FD06BE29290328AAA95F46243C5C30FBCEFFA7D7266767C0378B14BF5DA33C48` |
| `incrementalSave/` | 26ファイル。ユーザー保存履歴 |
| ルート `BifrostScales.mod` | SHA256 `6BADDD2D278243BD7EC3B337FE46F9ABAC5C2082C9E691B3447268B36906D287` |

ローカルmodは開発用の0.10.6絶対パスを含む。一方、Gitに保存する配布用modは0.10.9相対パス。
この差は意図して保持しており、ローカルmodをコミットしない。実機は上記modulesの0.10.9を使用。
作業前後にhashと件数を確認。ユーザーのMayaを終了したりシーンを上書きしない。
`git clean -fdx`、強制reset、広範囲削除は禁止。削除が必要なら対象一覧と復旧策を明示する。

## 4. 採用済み仕様（再導入・再解釈しない）

- Native Bifrostのみ。通常更新はpayload JSONとworldMesh接続。パラメータ更新ごとにGraphを編集しない。
- スライダー要求を集約し、不要なプレビュー評価を抑制。大量鱗のSystem選択中に重くなる問題は改善済み。
- Guide Outliner: 階層、複数選択、並べ替え、リネーム、Group、Maya選択同期、Typeリンク。
  表示/ロックは実クリックで機能。ガイド表示だけの変更で鱗を再生成しない。
  Ctrl+GとGuide/非Guide混在保護、ストローク中の軌跡表示を含む。
- スカルプト: Global/Scale Typeの両方。専用3Dビューは編集パッチのみ表示し、通常Viewportの表示を巻き込まない。
  外周・Gapは保持、内部を3方向へ編集可能。内部が外周の外へ張り出す形状や高さを圧縮しない。
  円盤ベースの編集メッシュと、外周へ沿わせても破綻しにくい内部トポロジー。
- Growthや2軸カーブの編集UI、Sculptに不要な旧パラメータは撤去。旧保存値の互換処理は残存箇所あり。
  これを理由に旧UIを復活させない。削除する場合は既存Sceneの見た目を比較する。
- 操作中表示はUI上Auto固定。Settled上限は自動、上限に達する場合は警告。
  手動Settled capとSettled Previewボタンは廃止。
- 実メッシュ化は**現在のプレビュー出力の独立コピー**。元System保持、Undo/Redo対応。
  プレビュー上限を超える全量Final出力ではない。標準マテリアルを割り当てる。
- UVは各鱗を0–1へ展開し、各枚のUVは重なる。同じテクスチャを各枚に使う仕様。
  Uの左右反転は修正済み。各faceのUV符号と全face割当を検証。
- 旧UVなしGraphはSystem選択時に一度更新。成功まで旧Graphを保持し、失敗時に参照を復旧。
- Curveの鱗方向への寄与を以前から180度反転。DirectionCurve/FlowCurve共通。
  Cell境界方向、密度、CV順、Point Guideの向きは変えていない。既存Curveにも適用する意図した変更。
- **独立Card機能は不採用・撤去済み。再実装しない。** 操作中の内部的な簡易表示とは別。
- UI: マウス向け縦一列、役割が明確なタブ、無彩色ダーク、赤寄りオレンジの操作点/主要ボタン。
  グレーの枠線なし、弱いドロップシャドウ。スマートフォン風カードやミント配色は不採用。
  Global/Typeとも「鱗をスカルプト」、アクセント色。日英切替、文字付きSVGアイコン。
  メンテナンス/Logは独立ウィンドウ。Maya全体のスタイルは変えない。

## 5. 検証済みと未検証を分ける

### 今回のコミット前に再実行（2026-09-18）

- Git indexから保護資産・生成物を含まないクリーンコピーを作成。
- Python **178/178 PASS、除外なし**。
- 同じクリーンコピーをCMakeで新規ビルドし、Native CTest **2/2 PASS**。
- コピー: `native/build/merge-source-64553cd5ab8f49e79c4f70b247c2145b/`（ローカル証跡、Git管理外）。
- ログ: `native/build/merge-clean-tests.log`, `merge-clean-native-config.log`,
  `merge-clean-native-build.log`, `merge-clean-native-tests.log`。
- 最初のpytest起動はPowerShell引数指定の問題で終了4。コピー内をcwdとして再実行し上記PASS。

### 直前の実機検証（2026-09-17、ログ保持）

- Installed Maya: UV左右反転の旧版FAIL→修正版PASS、各枚0–1、旧Graph更新と失敗復旧、
  メッシュ独立性、Undo/Redo。ガイドなしSculpt fixtureは2184頂点4080面、変更前後の形状完全一致。
- Installed Maya GUI: Guide/Group×表示/ロック×初期On/Offの8ケースPASS、shape_requests=0。
- Installed Qt: 言語変更で保存値不変、数値入力、Card撤去、Sculpt文言、Guideクリック4件PASS。
- 証跡: `native/build/mirror-after.log`, `mirror-guide-installed-result.json`,
  `mirror-native-tests.log`, `shadow-ui-ja.png`。
- Headless Maya起動のmenuSet/OpenGL警告は残存。成功ログと混同せず、正式版検証でも記録する。
- 最新版全体での**配布ZIPのクリーン生成・新規/更新/復旧/アンインストール再検証は未完了**。
  過去のBeta ZIPや以前の再現ビルド結果を、今回の正式版検証済み証拠に流用しない。

## 6. 次回の優先順（最終調整ゲート）

1. **公開仕様を固定**: 正式版番号、対応Maya/Bifrost範囲、実メッシュ出力がPreview範囲である制限を決める。
   UIの大幅改変や新規機能は増やさず、明確な不具合のみ対応。
2. **文書・メタデータ整合**: README/ROADMAP/ARCHITECTUREのBeta時点記述を更新。
   VERSION、配布mod、BUILD_INFO、manifest、installer、Native behavior識別子を一括確認する。
   現在Payload/Operator/Profileは10/20/11、Sceneは5、hostは`4-dgmesh-2-uv`。
   `vector-surface-6`等の識別子はUV/方向変更後も残るため、正式版で整理の要否を判断する。
3. **実機回帰**: 新規/既存複数System、保存/再起動、Guide/Group/混在Ctrl+G、Global/Type Sculpt、
   外周固定、張り出し/高さ、UV/前方、Graph移行、Undo/Redo、メッシュ出力を代表Sceneで通す。
   高密度System選択とスライダーの遅延、影の描画負荷、GPU cold/warmを同条件で測る。
4. **表示/翻訳の最終確認**: 全タブ、メンテナンス、Sculpt、警告/エラーの日本語/英語、
   DPI/窓幅/キーボードフォーカス、コンボ矢印。旧用語・未翻訳は実表示を見て修正。
5. **クリーン配布ビルド**: clean checkoutでNative Pack/OneClick ZIP生成、2回のhash比較。
   Python全件、Native全件、schema/native-only/release監査を通す。
   非エンジニア向けのビルド不要インストーラーを残す。ユーザー資産や旧配布物を混ぜない。
6. **隔離インストール検証→公開判断**: 新規導入、更新backup、旧Scene読み込み、復旧、アンインストール、
   再導入、installed DLL/hash一致、起動時catalog ready。すべて通ってからタグ/公開を行う。

旧runtimeや補助テストが不要に見えても、今回のコミット整理で無差別に削除していない。
最終整理は依存確認と保存Sceneの互換検証を伴う小さな変更に分ける。

## 7. 再現コマンドと参照先

まず `git status -sb`、`git log -3 --oneline --decorate`、保護資産hashを確認する。
開発PCのrootでは保護modとbuilt Packのため2件が環境依存になる。全件検証はクリーンコピーで実施。

```powershell
# クリーンコピーのルートで
python -m pytest tests --basetemp pytest-temp --tb=short
cmake -S native -B native/build -DBUILD_TESTING=ON -DBIFROST_SCALES_BUILD_BIFROST_OPERATOR=OFF
cmake --build native/build --config Release --parallel
ctest --test-dir native/build -C Release --output-on-failure
```

```powershell
# 開発PC、Mayaをユーザー自身が保存して終了した後。既存のconfigured buildを利用。
cmake --build BifrostScales/bifrost/out/maya2026-release --config Release --target install
python tools/install_dev_build.py --modules-dir C:\Users\takum\Documents\maya\modules
$env:PYTHONNOUSERSITE='1'
$env:MAYA_SKIP_USERSETUP_PY='1'
& 'C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe' tools/check_mesh_export_maya.py --installed
```

Qtだけの試験は`QT_QPA_PLATFORM=offscreen`とinstalled scriptsの`PYTHONPATH`を設定して
`tools/check_release_ui.py --installed`を実行。実Maya GUI試験前にoffscreenを解除する。
`check_guide_presentation_undo_maya.py`は**使い捨ての別Maya**で実行する（終了時quitするためユーザーのMayaでは実行禁止）。
過去の起動補助は`native/build/guide-checkbox-startup/userSetup.py`（Git管理外）。
必要時は検証スクリプトの入口を読んで、隔離MAYA_APP_DIR/userSetupを再作成する。

- Native build手順: `docs/NATIVE_BUILD_JA.md`
- 再現ビルド: `tools/check_native_build_reproducibility.py --output native/build/repro.json`
  （2回clean build。元modをfinallyで復元するが、保護hashの確認は別途行う）
- 配布ZIP: `tools/build_one_click_installer.py --output <新しい配布ZIPパス>`
- UI性能: `tools/measure_maya_slider_drag.py --help`（入力Sceneは上書きしない）
- 仕様/修正の詳細履歴: `docs/UI_UX_PRODUCT_HANDOFF_JA.md` の末尾から参照。
- 実装入口: `ui.py`/`ui_theme.py`、`sculpt_editor.py`/`sculpt_surface.py`、`scene.py`、
  `backend.py`/`native_backend.py`、`native/src/core.cpp`、Static Graph JSON。

**古い引き継ぎにある「UI/UX開発を最初から始める」「Cardや2軸カーブを作る」は実行しない。**
