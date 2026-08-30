# 0.10.6から0.10.7への移行

## 変更点

- 強いDensity Guideで固定Collision Marginが局所中心間隔を越えても、Cellが巨大なfallback半径へ開かないpair制約へ修正
- Cell外周の投影中点と法線をCacheし、内側リングと中心をTarget曲面へ追従
- 高曲率CellだけShape変形後に接続局所表面へexact再投影し、内側頂点のめり込みを防止
- 平面・緩曲面は軽量な曲面補間を維持し、Distribution／Orientation／Cell Cacheを再利用
- Operator Contract 18、Behavior Contractを0.10.7-density-margin-curvature-surface-follow-1へ更新

## 導入手順

1. BifrostScales_0_10_7_Standalone_Installer.pyをMaya Viewportへドラッグ＆ドロップします。
2. Mayaを完全に終了します。
3. 同梱PowerShellを-Cleanで実行します。
4. Mayaを再起動します。
5. Post Install Checkとdocs/MAYA_HOST_TEST_JA.mdを実行します。

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$HOME\Documents\maya\modules\BifrostScales\bifrost\tools\Build-BifrostScales-Native-Maya2026.ps1" -Clean
~~~

0.10.6 DLLは再利用できません。既存System、Settings、Guide、Group、Symmetry、Mask、Scale Types、Graph v4、worldMesh[0]接続は維持されます。

~~~text
product / pack / minimum  0.10.7
payload schema            bifrost-scales/native-payload/10
operator contract         bifrost-scales/operator-contract/18
behavior contract         bifrost-scales/native-core/0.10.7-density-margin-curvature-surface-follow-1
profile schema            bifrost-scales/native-profile/9
ready                     True
~~~
