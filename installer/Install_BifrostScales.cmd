@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Bifrost Scales Installer

tasklist /FI "IMAGENAME eq maya.exe" 2>nul | find /I "maya.exe" >nul
if not errorlevel 1 (
    echo Mayaが起動しています。Mayaを完全に終了してから再実行してください。
    echo.
    pause
    exit /b 2
)

set "INSTALL_SCRIPT=%~dp0installer\offline_install.py"
if not exist "%INSTALL_SCRIPT%" (
    echo インストーラー構成が不完全です: %INSTALL_SCRIPT%
    echo ZIPをすべて展開してから再実行してください。
    echo.
    pause
    exit /b 3
)

if not defined MAYA_LOCATION goto standard_maya_location
set "MAYAPY=%MAYA_LOCATION%\bin\mayapy.exe"
if exist "%MAYAPY%" goto run_installer

:standard_maya_location
set "MAYAPY=%ProgramFiles%\Autodesk\Maya2026\bin\mayapy.exe"
if exist "%MAYAPY%" goto run_installer

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%INSTALL_SCRIPT%"
    set "INSTALL_RESULT=!ERRORLEVEL!"
    goto finish
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%INSTALL_SCRIPT%"
    set "INSTALL_RESULT=!ERRORLEVEL!"
    goto finish
)

echo Maya 2026のmayapy、またはPython 3が見つかりません。
echo Maya 2026がインストール済みか確認してください。
set "INSTALL_RESULT=4"
goto finish

:run_installer
"%MAYAPY%" "%INSTALL_SCRIPT%"
set "INSTALL_RESULT=!ERRORLEVEL!"

:finish
echo.
if "!INSTALL_RESULT!"=="0" (
    echo インストールが完了しました。Maya 2026を起動して動作確認してください。
) else (
    echo インストールに失敗しました。上に表示された内容を確認してください。
)
echo.
if defined BIFROST_SCALES_INSTALLER_NO_PAUSE goto installer_done
pause

:installer_done
exit /b !INSTALL_RESULT!
