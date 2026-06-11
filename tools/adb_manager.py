#!/usr/bin/env python3
"""
ADB 管理模块
功能：自动检测、下载、安装 ADB
实现真正的开箱即用体验
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

# 配置
PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools" / "windows"
TEMP_DIR = PROJECT_ROOT / "tools" / ".temp"


def _print_progress(block_num: int, block_size: int, total_size: int):
    """打印下载进度"""
    downloaded = block_num * block_size
    percent = min(100, int(downloaded * 100 / total_size)) if total_size > 0 else 0
    mb = downloaded / 1024 / 1024
    total_mb = total_size / 1024 / 1024 if total_size > 0 else 0
    print(f"\r  进度: {percent}% ({mb:.1f}MB / {total_mb:.1f}MB)", end="", flush=True)


def check_system_adb() -> str | None:
    """检查系统 PATH 中是否有 ADB"""
    adb_path = shutil.which("adb")
    if adb_path:
        try:
            # 验证是否能正常运行
            result = subprocess.run(
                [adb_path, "version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return adb_path
        except Exception:
            pass
    return None


def check_builtin_adb() -> str | None:
    """检查项目内置 ADB"""
    adb_path = TOOLS_DIR / "adb.exe"
    if adb_path.exists():
        try:
            result = subprocess.run(
                [str(adb_path), "version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return str(adb_path)
        except Exception:
            pass
    return None


def download_and_install_adb(silent: bool = False) -> bool:
    """
    自动下载并安装 ADB 到项目目录
    
    Args:
        silent: 如果为 True，不打印详细信息（适合 GUI 调用）
    
    Returns:
        bool: 是否成功
    """
    if not silent:
        print("=" * 50)
        print("正在自动下载 ADB...")
        print("=" * 50)
        print(f"来源: {PLATFORM_TOOLS_URL}")
        print(f"许可证: Apache License 2.0")
        print()
    
    try:
        # 创建临时目录
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = TEMP_DIR / "platform-tools.zip"
        
        # 下载
        if not silent:
            print("[1/3] 下载中...")
        urlretrieve(PLATFORM_TOOLS_URL, zip_path, _print_progress)
        if not silent:
            print()  # 换行
        
        # 解压
        if not silent:
            print("[2/3] 解压中...")
        
        if TEMP_DIR.exists():
            # 清理旧的解压文件
            for item in TEMP_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(TEMP_DIR)
        
        # 查找 platform-tools 目录
        platform_tools_dir = None
        for item in TEMP_DIR.iterdir():
            if item.is_dir() and "platform-tools" in item.name.lower():
                platform_tools_dir = item
                break
        
        if not platform_tools_dir:
            if not silent:
                print("✗ 错误: 未找到 platform-tools 目录")
            return False
        
        # 创建目标目录
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 复制必要文件
        required_files = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]
        copied = []
        
        for filename in required_files:
            src = platform_tools_dir / filename
            dst = TOOLS_DIR / filename
            if src.exists():
                shutil.copy2(src, dst)
                copied.append(filename)
            else:
                if not silent:
                    print(f"  ⚠ 未找到: {filename}")
        
        # 清理
        zip_path.unlink(missing_ok=True)
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)
        
        if "adb.exe" not in copied:
            if not silent:
                print("✗ 错误: adb.exe 复制失败")
            return False
        
        # 验证
        if not silent:
            print("[3/3] 验证中...")
        
        adb_path = TOOLS_DIR / "adb.exe"
        result = subprocess.run(
            [str(adb_path), "version"],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode != 0:
            if not silent:
                print("✗ 验证失败")
            return False
        
        if not silent:
            version = result.stdout.decode('utf-8', errors='ignore').strip()
            print(f"✓ {version}")
            print()
            print("=" * 50)
            print("ADB 安装成功！")
            print("=" * 50)
        
        return True
        
    except Exception as e:
        if not silent:
            print(f"\n✗ 安装失败: {e}")
        return False


def ensure_adb_installed(auto_install: bool = True, silent: bool = False) -> tuple[bool, str]:
    """
    确保 ADB 已安装并可用
    
    优先级：
    1. 系统 ADB（如果可用）
    2. 内置 ADB（如果存在）
    3. 自动下载安装（如果 auto_install=True）
    
    Args:
        auto_install: 如果找不到 ADB，是否自动下载安装
        silent: 是否静默模式（适合 GUI 调用）
    
    Returns:
        tuple[bool, str]: (是否成功, ADB 路径或错误信息)
    """
    # 1. 检查系统 ADB
    system_adb = check_system_adb()
    if system_adb:
        if not silent:
            print(f"✓ 使用系统 ADB: {system_adb}")
        return True, system_adb
    
    # 2. 检查内置 ADB
    builtin_adb = check_builtin_adb()
    if builtin_adb:
        if not silent:
            print(f"✓ 使用内置 ADB: {builtin_adb}")
        return True, builtin_adb
    
    # 3. 自动下载安装
    if auto_install:
        if not silent:
            print("⚠ 未检测到 ADB，正在自动安装...")
            print()
        
        success = download_and_install_adb(silent=silent)
        if success:
            # 再次检查
            builtin_adb = check_builtin_adb()
            if builtin_adb:
                return True, builtin_adb
        
        if not silent:
            print("✗ 自动安装失败")
        return False, "ADB 自动安装失败，请检查网络连接或手动安装"
    
    return False, "未找到 ADB，且未启用自动安装"


def get_adb_path() -> str:
    """
    获取 ADB 路径（供其他模块调用）
    如果 ADB 未安装，会尝试自动安装
    
    Returns:
        str: ADB 可执行文件路径
    
    Raises:
        RuntimeError: 如果无法获取 ADB 路径
    """
    success, result = ensure_adb_installed(auto_install=True, silent=True)
    if success:
        return result
    raise RuntimeError(result)


def main():
    """命令行入口"""
    print("=" * 50)
    print("ADB 管理工具")
    print("=" * 50)
    print()
    
    # 检查当前状态
    print("检测 ADB 状态...")
    print()
    
    system_adb = check_system_adb()
    builtin_adb = check_builtin_adb()
    
    if system_adb:
        print(f"✓ 系统 ADB: {system_adb}")
    else:
        print("✗ 系统 ADB: 未找到")
    
    if builtin_adb:
        print(f"✓ 内置 ADB: {builtin_adb}")
    else:
        print("✗ 内置 ADB: 未找到")
    
    print()
    
    # 如果都没有，询问是否安装
    if not system_adb and not builtin_adb:
        response = input("是否自动下载并安装 ADB? (Y/n): ").strip().lower()
        if response in ('n', 'no'):
            print("已取消")
            return 0
        
        success, result = ensure_adb_installed(auto_install=True, silent=False)
        if success:
            print(f"\n✓ ADB 已就绪: {result}")
        else:
            print(f"\n✗ {result}")
            return 1
    else:
        print("ADB 已就绪，无需操作")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
