# 旧ツール削除ポリシー

## 削除するもの

- `MayaScales.mod`と対応する既知のmodule directory
- `BifrostScalesIntegration.mod`と対応するmodule directory
- `WoutScales.mod` / `WoutScales2026.mod`
- markerで検証されたWoutScales source / Pack directory
- `~/Autodesk/Bifrost/Compounds/MayaScales`

## 削除しないもの

- Maya scene file
- scene内のTarget Mesh
- Bake済みMesh
- 新Bifrost ScalesのSettings / Preview
- markerを確認できない任意の外部directory

## DLLがロード中の場合

WindowsではBifrost Operator DLLがMayaプロセスにロードされていると削除できません。Cleanupはmodule登録を先に削除し、失敗したpathを`BifrostScalesLegacyCleanupPending.json`へ保存します。Mayaを完全終了してから`BifrostScales_Complete_Legacy_Cleanup.py`を実行してください。
