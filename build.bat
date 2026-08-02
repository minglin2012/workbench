@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================
REM  工作台 — 一键打包脚本
REM  输出 dist/Workbench.exe + Workbench-Setup-x.x.x.exe
REM ============================================

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "VENV_PIP=%PROJECT_DIR%.venv\Scripts\pip.exe"
set "ISCC=iscc.exe"
set "DIST_DIR=%PROJECT_DIR%dist"

echo ========================================
echo   工作台 打包脚本
echo ========================================
echo.

REM ---- 检查依赖 ----
echo [1/5] 检查依赖...
if not exist "%VENV_PYTHON%" (
    echo 创建 .venv...
    python -m venv "%PROJECT_DIR%.venv"
)
"%VENV_PIP%" install -q fastapi uvicorn PyYAML pystray Pillow pywin32 psutil pyinstaller 2>&1 >nul
echo       依赖就绪.
echo.

REM ---- 清理旧构建 ----
echo [2/5] 清理旧构建...
if exist "%DIST_DIR%\Workbench.exe" del /q "%DIST_DIR%\Workbench.exe" 2>nul
if exist "%PROJECT_DIR%build" rmdir /s /q "%PROJECT_DIR%build" 2>nul
echo       清理完成.
echo.

REM ---- 构建 exe ----
echo [3/5] 构建 Workbench.exe...
call "%VENV_PYTHON%" -m PyInstaller "%PROJECT_DIR%workbench.spec" --noconfirm 2>&1 >nul
if errorlevel 1 (
    echo       构建失败! 请检查 workbench.spec
    pause
    exit /b 1
)
if not exist "%DIST_DIR%\Workbench.exe" (
    echo       构建失败! dist\Workbench.exe 未生成
    pause
    exit /b 1
)
for %%A in ("%DIST_DIR%\Workbench.exe") do set "EXE_SIZE=%%~zA"
set /a EXE_MB=%EXE_SIZE% / 1048576
echo       完成: Workbench.exe (%EXE_MB% MB)
echo.

REM ---- 获取版本号 ----
echo [4/5] 构建安装包...
for /f "tokens=*" %%V in ('"%VENV_PYTHON%" -c "import yaml; print('unknown')" 2^>nul') do set "VER=%%V"
set "VER=1.0.0"
"%ISCC%" "%PROJECT_DIR%installer.iss" 2>&1 >nul
if errorlevel 1 (
    echo       警告: 安装包构建失败，但 exe 已生成
) else (
    if exist "%DIST_DIR%\Workbench-Setup-%VER%.exe" (
        for %%A in ("%DIST_DIR%\Workbench-Setup-%VER%.exe") do set "SETUP_SIZE=%%~zA"
        set /a SETUP_MB=!SETUP_SIZE! / 1048576
        echo       完成: Workbench-Setup-%VER%.exe (!SETUP_MB! MB)
    )
)
echo.

REM ---- 完成 ----
echo [5/5] 打包完成!
echo.
echo   产物:
dir "%DIST_DIR%\Workbench*" /b 2>nul
echo.
echo   安装: 双击 Workbench-Setup-%VER%.exe
echo   便携: 直接运行 Workbench.exe
echo.
pause
