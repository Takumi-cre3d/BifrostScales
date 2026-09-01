# 0.10.8から0.10.9への移行

## 変更点

- Settled Distributionの近傍競合検索を同一セル、面、辺、角の順へ最適化
- 近傍検索順の最適化単独では候補順、乱数消費、距離判定、生成結果を維持
- distribution=時間(attempts)をNative Performanceログへ追加
- 0.10.8合成11,000枚基準でDistributionを245.5 msから142.9 msへ短縮
- 複数Density Guide時の候補受理分母を、評価済みDensity Fieldと同じ上限16へ修正
- Settledは三角形を面積×頂点Density上限で選び、三角形内だけでDensity補正
- Settledの競合グリッドは最低Densityを維持しつつ0.08を下限とし、局所的な低Densityによる過大バケットを抑制
- 三角形累積重み検索を検証付き65,536区間Indexで狭域化し、lower_boundの厳密な選択結果を維持
- Native Profileへ競合バケット検索数、距離比較数、実効グリッドDensityを追加
- 同じSpacingで1,024回以上連続競合した場合は次のSpacingへ進み、Final exact経路は従来どおり維持
- 固定低受理率テストで試行数983,040→241,695、枚数3,132→3,600
- 新ビルド内の決定性とStable Cell IDを維持（旧0.10.9開発ビルドとはSettled配置結果が変わる）
- Operator Contract 20、Profile Schema 11へ更新
- Behavior Contractを0.10.9-settled-proposal-index-1へ更新

## 導入手順

1. Mayaを完全に終了します。
2. 配布ZIPを展開し、Install_BifrostScales.cmdをダブルクリックします。
3. Mayaを再起動します。
4. Post Install Checkとdocs/MAYA_HOST_TEST_JA.mdを実行します。

0.10.8 DLLは再利用できません。既存System、Settings、Guide、Group、Symmetry、Mask、Scale Types、Graph v4、worldMesh[0]接続は維持されます。

~~~text
product / pack / minimum  0.10.9
payload schema            bifrost-scales/native-payload/10
operator contract         bifrost-scales/operator-contract/20
behavior contract         bifrost-scales/native-core/0.10.9-settled-proposal-index-1
profile schema            bifrost-scales/native-profile/11
ready                     True
~~~
