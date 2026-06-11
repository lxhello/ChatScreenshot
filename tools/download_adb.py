#!/usr/bin/env python3
"""
ADB 自动下载脚本
下载 Android Platform Tools (Windows) 到本地 tools/adb/ 目录
遵循 Apache 2.0 许可证要求
"""

import os
import sys
import zipfile
import urllib.request
import shutil
from pathlib import Path

# 官方下载地址
PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools" / "adb"
TEMP_DIR = PROJECT_ROOT / "tools" / ".temp"


def download_file(url: str, dest: Path, callback=None) -> bool:
    """下载文件并显示进度"""
    try:
        print(f"正在下载: {url}")
        print(f"目标位置: {dest}")
        
        def reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(100, int(downloaded * 100 / total_size)) if total_size > 0 else 0
            mb = downloaded / 1024 / 1024
            total_mb = total_size / 1024 / 1024 if total_size > 0 else 0
            print(f"\r进度: {percent}% ({mb:.1f}MB / {total_mb:.1f}MB)", end="", flush=True)
        
        urllib.request.urlretrieve(url, dest, reporthook)
        print()  # 换行
        return True
    except Exception as e:
        print(f"\n下载失败: {e}")
        return False


def extract_adb(zip_path: Path, extract_to: Path) -> bool:
    """解压并提取 ADB 相关文件"""
    try:
        print(f"正在解压: {zip_path}")
        
        # 清理并创建临时目录
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
        # 解压
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(TEMP_DIR)
        
        # 查找 platform-tools 目录
        platform_tools_dir = None
        for item in TEMP_DIR.iterdir():
            if item.is_dir() and "platform-tools" in item.name.lower():
                platform_tools_dir = item
                break
        
        if not platform_tools_dir:
            print("错误: 未找到 platform-tools 目录")
            return False
        
        # 创建目标目录
        extract_to.mkdir(parents=True, exist_ok=True)
        
        # 复制必要文件
        required_files = [
            "adb.exe",
            "AdbWinApi.dll",
            "AdbWinUsbApi.dll",
        ]
        
        copied = []
        for filename in required_files:
            src = platform_tools_dir / filename
            dst = extract_to / filename
            if src.exists():
                shutil.copy2(src, dst)
                copied.append(filename)
                print(f"  ✓ {filename}")
            else:
                print(f"  ✗ {filename} (未找到)")
        
        # 清理临时目录
        shutil.rmtree(TEMP_DIR)
        
        if "adb.exe" in copied:
            print(f"\nADB 安装成功: {extract_to}")
            return True
        else:
            print("\n错误: adb.exe 未成功复制")
            return False
            
    except Exception as e:
        print(f"解压失败: {e}")
        return False


def check_existing_adb() -> bool:
    """检查是否已存在 ADB"""
    adb_path = TOOLS_DIR / "adb.exe"
    if adb_path.exists():
        print(f"ADB 已存在: {adb_path}")
        return True
    return False


def check_system_adb() -> bool:
    """检查系统是否已有 ADB"""
    return shutil.which("adb") is not None


def main():
    print("=" * 50)
    print("ADB 自动下载工具")
    print("=" * 50)
    print()
    
    # 检查是否已有内置 ADB
    if check_existing_adb():
        print("内置 ADB 已安装，无需重复下载。")
        print(f"位置: {TOOLS_DIR / 'adb.exe'}")
        return 0
    
    # 检查系统 ADB
    if check_system_adb():
        print("检测到系统已安装 ADB，可以直接使用。")
        print("如需使用内置版本，请删除系统 ADB 或手动下载到 tools/adb/ 目录")
        response = input("是否仍要下载内置 ADB? (y/N): ").strip().lower()
        if response not in ('y', 'yes'):
            print("跳过下载，将使用系统 ADB")
            return 0
    
    print()
    print("即将下载 Android Platform Tools (Windows)")
    print("许可证: Apache License 2.0")
    print("来源: https://developer.android.com/studio/releases/platform-tools")
    print()
    
    # 确认下载
    response = input("确认下载? (Y/n): ").strip().lower()
    if response in ('n', 'no'):
        print("已取消")
        return 0
    
    print()
    
    # 创建临时目录
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = TEMP_DIR / "platform-tools.zip"
    
    # 下载
    if not download_file(PLATFORM_TOOLS_URL, zip_path):
        return 1
    
    print()
    
    # 解压
    if not extract_adb(zip_path, TOOLS_DIR):
        return 1
    
    # 清理
    if zip_path.exists():
        zip_path.unlink()
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    
    print()
    print("=" * 50)
    print("安装完成！")
    print("=" * 50)
    print(f"ADB 位置: {TOOLS_DIR / 'adb.exe'}")
    print()
    print("现在可以直接运行: python main.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
