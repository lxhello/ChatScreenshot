@echo off
chcp 65001 >nul
title ChatExtractor-Screenshot 发布打包工具
echo ============================================
echo ChatExtractor-Screenshot 发布打包工具
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 运行打包脚本
python "%~dp0prepare_release.py"
if errorlevel 1 (
    echo.
    echo [失败] 打包过程出错
    pause
    exit /b 1
)

echo.
pause
