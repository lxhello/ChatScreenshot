@echo off
chcp 65001 >nul
echo ============================================
echo ADB 自动下载工具
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 运行 Python 下载脚本
python "%~dp0download_adb.py"
if errorlevel 1 (
    echo.
    echo [失败] ADB 下载或安装失败
    pause
    exit /b 1
)

echo.
pause
