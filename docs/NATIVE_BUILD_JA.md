# Native Bifrost Pack ビルド手順 — 0.10.6

~~~text
Product / Native Pack    0.10.6
Payload                  bifrost-scales/native-payload/10
Operator                 bifrost-scales/operator-contract/18
Behavior                 bifrost-scales/native-core/0.10.6-cell-hot-path-1
Profile                  bifrost-scales/native-profile/9
Install Root             BifrostScalesCore-0.10.6
~~~

## 導入手順

Mayaを完全に終了してPowerShellで実行します。

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$HOME\Documents\maya\modules\BifrostScales\bifrost\tools\Build-BifrostScales-Native-Maya2026.ps1" -Clean
~~~

Visual Studio、Maya 2026 Bifrost SDK、CMakeを検出し、Release DLL、Node Definition、Static Graph、Manifestと診断CLIをインストールします。OpenCL SDKは不要です。

## 検証手順

~~~powershell
$tools = "$HOME\Documents\maya\modules\BifrostScales\bifrost\native\out\BifrostScalesCore-0.10.6\tools"
& "$tools\bifrost_scales_stage_cache_benchmark.exe" 10000
& "$tools\bifrost_scales_performance_benchmark.exe" 30000
& "$tools\bifrost_scales_gpu_preview_benchmark.exe" 10000
~~~

Stage Cacheはcache_scope=process-shared-bounded、3 Stageのhitとexactがtrueなら合格です。GPU環境ではgpu_used:true、GPUなしでは理由付きCPU fallbackとsettled_cpu_exact:trueが合格です。Performanceは同じPCで0.10.5と5回比較してください。
