# ワンクリックインストーラー

`tools/build_one_click_installer.py`は、Maya 2026／Bifrost 2.15向けにビルド済みのNative Packと製品Runtimeを、Windows用の配布ZIPへまとめます。

## 配布物の生成

Maya 2026用Native Packを先にビルドし、次を実行します。

```powershell
python tools/build_one_click_installer.py
```

生成物:

- `dist/BifrostScales_0_10_6_OneClick_Installer.zip`
- `dist/BifrostScales_0_10_6_OneClick_Installer.zip.sha256`

ローカル固有の`BifrostScales.mod`は配布物へ使用しません。Module定義は正規化され、インストール時に対象PCのPackConfig絶対パスを登録します。

## 他PCへの導入

1. ZIPをすべて展開します。
2. Mayaを完全に終了します。
3. `Install_BifrostScales.cmd`をダブルクリックします。
4. 完了後にMaya 2026を起動します。

インストーラーはMaya 2026付属の`mayapy.exe`を優先使用し、Windows x64、Maya 2026、Maya 2026用Bifrostを確認します。Payload全ファイルをSHA-256検証してから既存版を日時付きフォルダへ移動し、新版のコピー後にも再検証します。失敗時は以前のPackageとModule定義を復元します。

## 導入後の確認

Maya Script Editorで次を実行します。

```python
import bifrost_scales
print(bifrost_scales.__version__)
bifrost_scales.show()
```

`0.10.6`が表示され、UIからSystemを作成できることを確認します。Native Performanceログでは、Directionだけを再編集した際に`neighborCache=hit`が表示されます。
