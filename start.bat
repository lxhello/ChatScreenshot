@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo ChatExtractor-Screenshot 启动器
echo ============================================
echo.

if exist "%~dp0ChatExtractor.exe" (
    start "" "%~dp0ChatExtractor.exe"
    exit /b 0
)

if exist "%~dp0dist\ChatExtractor\ChatExtractor.exe" (
    start "" "%~dp0dist\ChatExtractor\ChatExtractor.exe"
    exit /b 0
)

if exist "main.py" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未检测到 Python，请先安装 Python 3.10+
        echo 或直接运行 dist\ChatExtractor\ChatExtractor.exe
        pause
        exit /b 1
    )

    python "%~dp0main.py"
    exit /b %ERRORLEVEL%
)

echo [错误] 未找到 ChatExtractor.exe 或 main.py
pause
exit /b 1
