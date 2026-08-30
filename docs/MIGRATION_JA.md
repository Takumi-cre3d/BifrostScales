# 0.10.7から0.10.8への移行

## 変更点

- Target MeshとGuideの形状・Rangeが変わらない限り、表面接続距離FieldをGuide単位で再利用
- 1本のGuide編集では変更されたGuideのFieldだけを再構築
- Interactive候補生成用のTarget面積累積表と法線表を編集間で再利用
- `guideSurface=時間(hit/miss)`と`meshSample=hit|miss`をNative Performanceログへ追加
- 配置結果、Stable Cell ID、Settled／Finalの決定性は0.10.7と同一
- Operator Contract 19、Behavior Contractを0.10.8-surface-guide-sampling-cache-1へ更新

## 導入手順

1. Mayaを完全に終了します。
2. 配布ZIPを展開し、`Install_BifrostScales.cmd`をダブルクリックします。
3. Mayaを再起動します。
4. Post Install Checkとdocs/MAYA_HOST_TEST_JA.mdを実行します。

0.10.7 DLLは再利用できません。既存System、Settings、Guide、Group、Symmetry、Mask、Scale Types、Graph v4、worldMesh[0]接続は維持されます。

~~~text
product / pack / minimum  0.10.8
payload schema            bifrost-scales/native-payload/10
operator contract         bifrost-scales/operator-contract/19
behavior contract         bifrost-scales/native-core/0.10.8-surface-guide-sampling-cache-1
profile schema            bifrost-scales/native-profile/10
ready                     True
~~~
