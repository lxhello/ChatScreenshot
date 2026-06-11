@echo off
setlocal
echo PyInstaller 打包 — ChatExtractor

REM 检查 pyinstaller
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
  echo 请先在当前环境安装 PyInstaller: pip install pyinstaller
  exit /b 1
)

REM 使用 spec 文件进行构建（参数以 spec 为准）
python -m PyInstaller --clean --noconfirm ChatExtractor.spec

if %ERRORLEVEL% neq 0 (
  echo 打包失败
  exit /b %ERRORLEVEL%
)

copy /Y start.bat dist\start.bat >nul

echo 打包完成: dist\ChatExtractor\ChatExtractor.exe
exit /b 0
