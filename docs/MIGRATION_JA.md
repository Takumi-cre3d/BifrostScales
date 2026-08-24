# 0.10.5から0.10.6への移行

## 変更点

- exact Cell PartitionのRay角度、Normal、Surface Componentを共有／事前計算
- Mask GuideがないときのCell Ray Mask判定を完全スキップ
- 廃止済みDirection Pair用Partition構造を1 Sample = 1 Siteへ整理
- Mesh、Cell境界、Stable Cell ID、乱数、倍精度Settled結果は0.10.5とbyte-exact
- 0.10.5のStage Cache／Distribution Index、GPU Orientation、開放エッジDensity適応を維持
- Operator Contract 18、Behavior Contractを0.10.6-cell-hot-path-1へ更新

## 導入手順

1. BifrostScales_0_10_6_Standalone_Installer.pyをMaya Viewportへドラッグ＆ドロップします。
2. Mayaを完全に終了します。
3. 同梱PowerShellを-Cleanで実行します。
4. Mayaを再起動します。
5. Post Install Checkとdocs/MAYA_HOST_TEST_JA.mdを実行します。

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$HOME\Documents\maya\modules\BifrostScales\bifrost\tools\Build-BifrostScales-Native-Maya2026.ps1" -Clean
~~~

0.10.5 DLLは再利用できません。既存System、Settings、Guide、Group、Symmetry、Mask、Scale Types、Unique Scale登録、Graph v4、worldMesh[0]接続は維持されます。

~~~text
product / pack / minimum  0.10.6
payload schema            bifrost-scales/native-payload/10
operator contract         bifrost-scales/operator-contract/18
behavior contract         bifrost-scales/native-core/0.10.6-cell-hot-path-1
profile schema            bifrost-scales/native-profile/9
ready                     True
~~~
