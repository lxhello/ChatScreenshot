#!/usr/bin/env python3
"""
发布打包脚本 - 将 ADB 集成到项目中
适合没有技术基础的用户，开箱即用
"""

import os
import sys
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools" / "adb"

def find_system_adb() -> Path | None:
    """查找系统中的 ADB"""
    adb_path = shutil.which("adb")
    if adb_path:
        return Path(adb_path)
    
    # 检查常见的安装位置
    common_paths = [
        Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path("C:") / "Program Files" / "platform-tools" / "adb.exe",
        Path("C:") / "platform-tools" / "adb.exe",
        Path("D:") / "platform-tools" / "adb.exe",
    ]
    for path in common_paths:
        if path.exists():
            return path
    return None


def find_adb_dlls(adb_path: Path) -> list[Path]:
    """查找 ADB 所需的 DLL 文件"""
    adb_dir = adb_path.parent
    dlls = []
    for dll_name in ["AdbWinApi.dll", "AdbWinUsbApi.dll"]:
        dll_path = adb_dir / dll_name
        if dll_path.exists():
            dlls.append(dll_path)
    return dlls


def copy_adb_to_project(adb_path: Path) -> bool:
    """复制 ADB 到项目目录"""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"找到 ADB: {adb_path}")
    print(f"目标目录: {TOOLS_DIR}")
    print()
    
    # 复制 adb.exe
    dest_adb = TOOLS_DIR / "adb.exe"
    shutil.copy2(adb_path, dest_adb)
    print(f"✓ 已复制: adb.exe")
    
    # 复制 DLL 文件
    dlls = find_adb_dlls(adb_path)
    for dll_path in dlls:
        dest_dll = TOOLS_DIR / dll_path.name
        shutil.copy2(dll_path, dest_dll)
        print(f"✓ 已复制: {dll_path.name}")
    
    if len(dlls) < 2:
        print(f"⚠ 警告: 部分 DLL 文件未找到，可能影响某些设备连接")
    
    print()
    return True


def check_existing() -> bool:
    """检查是否已有内置 ADB"""
    adb_path = TOOLS_DIR / "adb.exe"
    if adb_path.exists():
        print(f"✓ 项目已包含 ADB: {adb_path}")
        print(f"  文件大小: {adb_path.stat().st_size / 1024:.1f} KB")
        return True
    return False


def create_release_package():
    """创建发布压缩包"""
    import zipfile
    from datetime import datetime
    
    # 生成版本号（基于日期）
    version = datetime.now().strftime("%Y%m%d")
    zip_name = f"ChatExtractor-Screenshot-v{version}.zip"
    zip_path = PROJECT_ROOT.parent / zip_name
    
    print(f"正在创建发布包: {zip_name}")
    print()
    
    # 创建 zip 文件
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # 跳过不需要的目录
            dirs[:] = [d for d in dirs if d not in [
                '__pycache__', '.venv', '.git', '.temp', 'projects'
            ]]
            
            for file in files:
                # 跳过不需要的文件
                if file.endswith(('.pyc', '.log')):
                    continue
                
                file_path = Path(root) / file
                arc_name = file_path.relative_to(PROJECT_ROOT.parent)
                zf.write(file_path, arc_name)
                print(f"  + {arc_name}")
    
    print()
    print(f"✓ 发布包已创建: {zip_path}")
    print(f"  文件大小: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    return zip_path


def main():
    print("=" * 60)
    print("ChatExtractor-Screenshot 发布打包工具")
    print("=" * 60)
    print()
    
    # 检查是否已有内置 ADB
    if check_existing():
        print()
        response = input("是否重新复制 ADB? (y/N): ").strip().lower()
        if response not in ('y', 'yes'):
            print("使用现有的 ADB")
        else:
            # 删除旧的
            if TOOLS_DIR.exists():
                shutil.rmtree(TOOLS_DIR)
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    else:
        print("项目尚未包含 ADB")
    
    # 检查是否需要复制 ADB
    if not (TOOLS_DIR / "adb.exe").exists():
        print()
        print("查找系统中的 ADB...")
        adb_path = find_system_adb()
        
        if adb_path:
            print(f"✓ 找到系统 ADB: {adb_path}")
            print()
            response = input("是否将此 ADB 复制到项目中? (Y/n): ").strip().lower()
            if response not in ('n', 'no'):
                copy_adb_to_project(adb_path)
            else:
                print("请手动将以下文件复制到 tools/adb/ 目录:")
                print("  - adb.exe")
                print("  - AdbWinApi.dll")
                print("  - AdbWinUsbApi.dll")
                return 0
        else:
            print("✗ 未找到系统 ADB")
            print()
            print("请手动将 ADB 文件复制到 tools/adb/ 目录:")
            print("1. 访问 https://developer.android.com/studio/releases/platform-tools")
            print("2. 下载 Windows 版本并解压")
            print(f"3. 将以下文件复制到: {TOOLS_DIR}")
            print("   - adb.exe")
            print("   - AdbWinApi.dll")
            print("   - AdbWinUsbApi.dll")
            return 1
    
    # 验证 ADB
    adb_exe = TOOLS_DIR / "adb.exe"
    if adb_exe.exists():
        print("=" * 60)
        print("验证 ADB...")
        result = os.system(f'"{adb_exe}" version')
        if result == 0:
            print("✓ ADB 可正常运行")
        else:
            print("✗ ADB 验证失败")
            return 1
    
    print()
    print("=" * 60)
    print("打包完成！")
    print("=" * 60)
    print()
    print(f"现在你可以将整个项目文件夹压缩分享给别人")
    print(f"用户只需双击 run.bat 即可使用，无需安装 ADB")
    print()
    
    # 询问是否创建 zip 包
    response = input("是否自动创建 zip 压缩包? (y/N): ").strip().lower()
    if response in ('y', 'yes'):
        print()
        zip_path = create_release_package()
        print()
        print("=" * 60)
        print("发布包创建成功！")
        print("=" * 60)
        print(f"文件: {zip_path}")
        print()
        print("分享方式:")
        print("1. 直接发送 .zip 文件给别人")
        print("2. 或者将整个项目文件夹复制给别人")
        print()
        print("用户使用步骤:")
        print("1. 解压 zip 文件")
        print("2. 双击 run.bat")
        print("3. 按提示连接手机即可使用")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
