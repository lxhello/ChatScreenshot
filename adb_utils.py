"""ADB 工具模块 - 设备连接、App识别、截图、滚动"""

from __future__ import annotations

import os
import re
import importlib
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageStat

try:
    APK = importlib.import_module("apkutils2").APK
except Exception:  # pragma: no cover - 可选依赖
    APK = None


# ==================== ADB 路径管理 ====================

_WINDOWS_SUBPROCESS_KWARGS = {}
if os.name == "nt":
    _WINDOWS_SUBPROCESS_KWARGS = {
        "startupinfo": subprocess.STARTUPINFO(),
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }
    _WINDOWS_SUBPROCESS_KWARGS["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW

def _get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).parent.resolve()

def _get_adb_path() -> str:
    """
    获取 ADB 可执行文件路径。
    仅使用项目内置 ADB (tools/adb/adb.exe)。
    """
    project_root = _get_runtime_root()
    builtin_adb = project_root / "tools" / "adb" / "adb.exe"
    return str(builtin_adb)


# 全局 ADB 路径缓存
_ADB_PATH = _get_adb_path()


class AdbError(RuntimeError):
    """ADB 相关错误基类"""


class AdbNotFoundError(AdbError):
    """系统中找不到 adb 命令"""


class AdbTimeoutError(AdbError):
    """ADB 命令执行超时"""


class AdbNoDeviceError(AdbError):
    """未检测到可用设备"""


class AdbUnauthorizedError(AdbError):
    """设备存在但未授权 USB 调试"""


class AdbCommandError(AdbError):
    """ADB 命令执行失败"""


@dataclass
class AdbResult:
    args: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode(errors="ignore")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode(errors="ignore")

    @property
    def output_text(self) -> str:
        return f"{self.stdout_text}\n{self.stderr_text}".strip()


def _format_adb_args(args: list[str]) -> str:
    return "adb " + " ".join(str(part) for part in args)


def _build_adb_not_found_message() -> str:
    """构建 ADB 未找到的友好提示信息"""
    project_root = _get_runtime_root()
    
    lines = [
        "未找到项目内置 adb.exe！",
        "",
        "解决方案（选择其一）：",
        "",
        "【推荐】方案一：自动下载内置 ADB",
        "  1. 双击运行: tools/download_adb.bat",
        "  2. 按提示完成下载到项目目录",
        "",
        "方案二：手动放置 adb",
        f"  1. 将 adb.exe 放到: {project_root / 'tools' / 'adb'}",
        "  2. 同目录保留 AdbWinApi.dll 和 AdbWinUsbApi.dll",
        "",
        "完成后重新运行程序。",
    ]
    return "\n".join(lines)


def _raise_adb_error(args: list[str], message: str, error_cls: type[AdbError] = AdbCommandError):
    raise error_cls(f"{message}\n命令: {_format_adb_args(args)}")


def _check_device_lines(output: str):
    lines = output.strip().splitlines()[1:]
    devices: list[str] = []
    unauthorized: list[str] = []
    offline: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "\tdevice" in line:
            devices.append(line.split("\t", 1)[0])
        elif "\tunauthorized" in line:
            unauthorized.append(line.split("\t", 1)[0])
        elif "\toffline" in line:
            offline.append(line.split("\t", 1)[0])

    if devices:
        return devices[0]
    if unauthorized:
        raise AdbUnauthorizedError(f"检测到设备但未授权 USB 调试：{', '.join(unauthorized)}")
    if offline:
        raise AdbNoDeviceError(f"检测到设备离线：{', '.join(offline)}")
    raise AdbNoDeviceError("未检测到 Android 设备")


def run_adb(args: list, timeout: int = 10, check: bool = True, device_id: str | None = None) -> AdbResult:
    """执行 ADB 命令，并统一转换为明确的错误类型。"""
    global _ADB_PATH
    
    # 如果指定了设备 ID，就在命令中加入 -s 参数
    actual_args = args
    if device_id and args != ["devices"]:
        actual_args = ["-s", device_id] + args
    
    try:
        completed = subprocess.run(
            [_ADB_PATH] + actual_args,
            capture_output=True,
            timeout=timeout,
            **_WINDOWS_SUBPROCESS_KWARGS,
        )
    except FileNotFoundError as exc:
        # 构建友好的错误提示
        error_msg = _build_adb_not_found_message()
        raise AdbNotFoundError(error_msg) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeoutError(f"ADB 命令执行超时（>{timeout}s）\n命令: {_format_adb_args(actual_args)}") from exc

    result = AdbResult(
        args=[str(part) for part in actual_args],
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )

    if not check:
        return result

    combined = result.output_text.lower()
    if args == ["devices"]:
        _check_device_lines(result.stdout_text)
        return result

    # 如果检测到多设备错误且还没有指定设备ID，尝试自动获取并重试
    if "more than one device/emulator" in combined and not device_id:
        try:
            device_id = check_device()
            # 重新调用 run_adb 并指定设备ID
            return run_adb(args, timeout=timeout, check=check, device_id=device_id)
        except Exception:
            pass  # 如果自动获取设备ID失败，就继续处理原错误

    if "unauthorized" in combined:
        _raise_adb_error(args, "设备已连接但未授权 USB 调试，请在手机上确认授权", AdbUnauthorizedError)
    if any(token in combined for token in ["no devices/emulators found", "device offline", "more than one device/emulator"]):
        _raise_adb_error(args, "当前没有可用设备，或设备状态异常", AdbNoDeviceError)
    if result.returncode != 0:
        detail = result.output_text or f"返回码 {result.returncode}"
        _raise_adb_error(args, f"ADB 命令执行失败：{detail}")

    return result


def check_device() -> str:
    """检查设备连接，返回设备 ID；失败时抛出明确异常。"""
    result = run_adb(["devices"], timeout=8, check=False)
    if result.returncode != 0:
        detail = result.output_text or f"返回码 {result.returncode}"
        _raise_adb_error(["devices"], f"获取设备列表失败：{detail}")
    return _check_device_lines(result.stdout_text)


def get_screen_resolution() -> tuple[int, int]:
    """获取屏幕分辨率"""
    result = run_adb(["shell", "wm", "size"], timeout=6)
    matches = re.findall(r"(\d+)x(\d+)", result.stdout_text)
    if matches:
        width, height = matches[-1]
        return int(width), int(height)
    _raise_adb_error(["shell", "wm", "size"], f"无法解析屏幕分辨率：{result.stdout_text.strip()}")


def get_device_profile() -> dict:
    """获取设备标识、品牌、型号与用于目录命名的设备名。"""
    device_id = check_device()
    keys = {
        "manufacturer": "ro.product.manufacturer",
        "brand": "ro.product.brand",
        "model": "ro.product.model",
        "market_name": "ro.product.marketname",
        "device": "ro.product.device",
    }
    values: dict[str, str] = {}
    for field, prop in keys.items():
        try:
            result = run_adb(["shell", "getprop", prop], timeout=6)
            values[field] = result.stdout_text.strip()
        except Exception:
            values[field] = ""

    manufacturer = values.get("manufacturer", "").strip()
    brand = values.get("brand", "").strip()
    model = values.get("model", "").strip()
    market_name = values.get("market_name", "").strip()
    device = values.get("device", "").strip()

    vendor = manufacturer or brand or "Android"
    display_model = market_name or model or device or device_id
    folder_parts: list[str] = []
    if vendor:
        folder_parts.append(vendor)
    if display_model and display_model.lower() != vendor.lower():
        folder_parts.append(display_model)
    folder_name = "_".join(part.strip() for part in folder_parts if part.strip()) or device_id
    folder_name = re.sub(r"\s+", "_", folder_name)
    folder_name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", folder_name).strip("_") or device_id

    return {
        "device_id": device_id,
        "manufacturer": manufacturer,
        "brand": brand,
        "model": model,
        "market_name": market_name,
        "device": device,
        "folder_name": folder_name,
        "display_name": f"{vendor} {display_model}".strip(),
    }


def get_current_app() -> dict:
    """获取当前前台 App 信息"""
    result = run_adb(["shell", "dumpsys", "activity", "recents"], timeout=12)
    output = result.stdout_text

    package = None
    match = re.search(r"Recent #0.*?baseIntent.*?cmp=([^\s/]+)", output, re.DOTALL)
    if match:
        package = match.group(1)

    if not package:
        result2 = run_adb(["shell", "dumpsys", "window", "displays"], timeout=12)
        match2 = re.search(r"mCurrentFocus.*?(\w+\.\w+[\.\w]*)/", result2.stdout_text)
        if match2:
            package = match2.group(1)

    if not package:
        raise AdbCommandError("未能识别当前前台 App，请先打开目标应用到前台")

    app_name = get_app_name(package)
    return {"package": package, "app_name": app_name}


def _normalize_app_label(package: str, value: str) -> str:
    text = (value or "").strip().strip("'").strip('"')
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""

    lowered = text.lower()
    package_lower = package.lower()
    package_leaf = package.split(".")[-1].lower()

    if lowered == package_lower:
        return ""
    if lowered in {package_leaf, "main", "defaulticon", "launcher", "launch"}:
        return ""
    if text.startswith("@"):
        return ""
    if re.fullmatch(r"[a-z0-9_.$-]+", text, re.IGNORECASE) and "." in text:
        return ""
    return text



def _decode_manifest_label_value(apk_path: str, package: str) -> str:
    if APK is None:
        return ""

    try:
        apk = APK(apk_path)
        manifest = apk.get_manifest() or {}
        application = manifest.get("application") or {}
        raw_label = application.get("@android:label")
        if not raw_label:
            return ""

        normalized_raw = _normalize_app_label(package, str(raw_label))
        if normalized_raw:
            return normalized_raw

        if not isinstance(raw_label, str) or not raw_label.startswith("@"):
            return ""

        arsc = apk.get_arsc()
        package_names = []
        try:
            package_names = list(arsc.get_packages_names() or [])
        except Exception:
            package_names = []

        target_package_names = [name for name in [package, *package_names] if name]
        resource_name = None
        for package_name in target_package_names:
            try:
                resource_name = arsc.get_id(package_name, int(raw_label[1:], 16))
            except Exception:
                continue
            if resource_name:
                break

        if not resource_name:
            return ""

        if isinstance(resource_name, tuple):
            if len(resource_name) >= 2:
                name_only = str(resource_name[1])
            else:
                return ""
        else:
            name_only = str(resource_name).split("/", 1)[-1]

        locales = ["\x00\x00", "en", "zh-CN", "zh-rCN", "zh"]
        for package_name in target_package_names:
            for locale in locales:
                try:
                    resolved = arsc.get_string(package_name, name_only, locale)
                except Exception:
                    continue
                if isinstance(resolved, (list, tuple)):
                    resolved_value = resolved[-1] if resolved else ""
                else:
                    resolved_value = resolved
                label = _normalize_app_label(package, str(resolved_value))
                if label:
                    return label
    except Exception:
        return ""

    return ""



def _get_app_name_from_apk(package: str) -> str:
    if APK is None:
        return ""

    try:
        apk_paths = get_package_apk_paths(package)
    except AdbError:
        return ""
    # Try all APK paths returned by `pm path` (handle split APKs and non-base names).
    for remote_path in apk_paths:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            run_adb(["pull", remote_path, tmp_path], timeout=90)
            label = _decode_manifest_label_value(tmp_path, package)
            if label:
                return label
        except AdbError:
            # try next APK path
            continue
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    return ""



def get_app_name(package: str) -> str:
    """通过包名获取 App 显示名称；优先解析 APK 资源，避免把 Activity 类名误当应用名。"""
    package = package.strip()
    if not package:
        return "未识别"

    apk_label = _get_app_name_from_apk(package)
    if apk_label:
        return apk_label

    patterns = [
        r"application-label(?:-[\w]+)?:'([^']+)'",
        r"nonLocalizedLabel=([^\n]+)",
        r"label=([^\n]+)",
        r"android:label\([^)]*\)=\"([^\"]+)\"",
        r"android:label\([^)]*\)=([^\n]+)",
        r"ApplicationInfo\{[^\n]*\}\s*label=([^\n]+)",
    ]

    try:
        dump_result = run_adb(["shell", "dumpsys", "package", package], timeout=15, check=False)
        dump_text = dump_result.output_text
        for pattern in patterns:
            for match in re.finditer(pattern, dump_text, re.DOTALL):
                label = _normalize_app_label(package, match.group(1))
                if label:
                    return label
    except AdbError:
        pass

    return f"未识别（{package}）"


def get_install_source(package: str) -> str:
    """获取应用安装来源（单包回退，尽量少用）"""
    result = run_adb(["shell", "cmd", "package", "list", "packages", "-i", package], timeout=6)
    match = re.search(rf"package:{re.escape(package)}\s+installer=([^\s]+)", result.stdout_text)
    if match:
        source = match.group(1).strip().strip('"')
        if source and source not in {"null", "none", "unknown"}:
            return _pretty_install_source(source)
    return "系统安装 / 未知"


def _iter_package_lines(output: str):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            yield line


def _parse_package_line(line: str) -> dict | None:
    match = re.search(r"package:([^\s]+)", line)
    if not match:
        return None
    package = match.group(1).strip()

    installer_match = re.search(r"installer=([^\s]+)", line)
    installer = installer_match.group(1).strip().strip('"') if installer_match else ""
    if installer and installer not in {"null", "none", "unknown"}:
        source = _pretty_install_source(installer)
    else:
        source = "系统安装 / 未知"

    uid_match = re.search(r"uid:(\d+)", line)
    uid = int(uid_match.group(1)) if uid_match else None

    return {
        "name": "",
        "package": package,
        "source": source,
        "uid": uid,
    }


def _pretty_install_source(source: str) -> str:
    mapping = {
        "com.android.vending": "Google Play",
        "com.huawei.appmarket": "华为应用市场",
        "com.sec.android.app.samsungapps": "Samsung Galaxy Store",
        "com.xiaomi.market": "小米应用商店",
        "com.oppo.market": "OPPO 应用商店",
        "com.heytap.market": "OPPO 应用商店",
        "com.vivo.appstore": "vivo 应用商店",
        "com.amazon.venezia": "Amazon Appstore",
    }
    return mapping.get(source, source)


_APP_NAME_CACHE: dict[str, str] = {}
_APP_NAME_CACHE_LOCK = threading.Lock()


def _get_cached_app_name(package: str) -> str:
    with _APP_NAME_CACHE_LOCK:
        cached = _APP_NAME_CACHE.get(package)
    if cached:
        return cached

    try:
        label = get_app_name(package)
    except Exception:
        label = f"未识别（{package}）"

    label = (label or f"未识别（{package}）").strip()
    with _APP_NAME_CACHE_LOCK:
        _APP_NAME_CACHE[package] = label
    return label


def list_installed_apps(include_system: bool = True) -> list[dict]:
    """列出已安装应用（名称 / 包名 / 安装来源）。优先一次性快速取包列表，名称按缓存/轻量回退补齐，避免大量 ADB 并发导致卡顿。"""
    args = ["shell", "cmd", "package", "list", "packages", "-i", "-U"]
    if not include_system:
        args.insert(-2, "-3")

    apps: list[dict] = []
    try:
        result = run_adb(args, timeout=20)
        for line in _iter_package_lines(result.stdout_text):
            parsed = _parse_package_line(line)
            if parsed:
                apps.append(parsed)
    except AdbCommandError:
        pass

    if not apps:
        fallback_args = ["shell", "pm", "list", "packages"]
        if not include_system:
            fallback_args.append("-3")
        fallback_result = run_adb(fallback_args, timeout=25)
        for line in _iter_package_lines(fallback_result.stdout_text):
            parsed = _parse_package_line(line)
            if parsed:
                apps.append(parsed)

    if not apps:
        return []

    unresolved_packages: list[str] = []
    with _APP_NAME_CACHE_LOCK:
        for app in apps:
            package = app["package"]
            cached = _APP_NAME_CACHE.get(package)
            if cached:
                app["name"] = cached
            else:
                app["name"] = f"未识别（{package}）"
                unresolved_packages.append(package)

    max_resolve = 24 if include_system else 40
    for package in unresolved_packages[:max_resolve]:
        resolved_name = _get_cached_app_name(package)
        for app in apps:
            if app["package"] == package:
                app["name"] = resolved_name
                break

    apps.sort(key=lambda item: (item["name"].lower(), item["package"].lower()))
    return apps


def start_screen_record(remote_path: str = "/sdcard/Download/0xsec_record.mp4", bit_rate: int = 8000000):
    """启动 Android 原生 screenrecord，返回后台进程对象和远端路径"""
    global _ADB_PATH
    try:
        process = subprocess.Popen(
            [
                _ADB_PATH,
                "shell",
                "screenrecord",
                "--bit-rate",
                str(bit_rate),
                remote_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_WINDOWS_SUBPROCESS_KWARGS,
        )
    except FileNotFoundError as exc:
        error_msg = _build_adb_not_found_message()
        raise AdbNotFoundError(error_msg) from exc
    time.sleep(0.6)
    return process, remote_path


def _get_remote_file_size(remote_path: str) -> int:
    result = run_adb(["shell", "stat", "-c", "%s", remote_path], timeout=8, check=False)
    text = result.stdout_text.strip()
    try:
        size = int(text)
    except (TypeError, ValueError):
        return -1
    return size if size >= 0 else -1


def _wait_for_remote_recording_file_ready(remote_path: str, stop_timeout: int = 8) -> int:
    """等待远端录屏文件稳定，避免 mp4 尚未 flush 完就被拉取。"""
    stable_hits = 0
    last_size = -1
    deadline = time.time() + max(4, stop_timeout)
    while time.time() < deadline:
        size = _get_remote_file_size(remote_path)
        if size <= 0:
            time.sleep(0.35)
            continue
        if size == last_size:
            stable_hits += 1
            if stable_hits >= 2:
                return size
        else:
            stable_hits = 0
            last_size = size
        time.sleep(0.35)
    return last_size


def _looks_like_complete_mp4(path: str | Path) -> bool:
    """轻量校验 mp4 基本结构，避免把未完整收尾的半成品误判为成功。"""
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size < 32:
            return False
        size = path.stat().st_size
        with path.open("rb") as fh:
            head = fh.read(min(256, size))
            if b"ftyp" not in head:
                return False
            tail_size = min(512 * 1024, size)
            fh.seek(max(0, size - tail_size))
            tail = fh.read(tail_size)
        has_moov = b"moov" in tail or b"moov" in head
        has_mdat = b"mdat" in tail or b"mdat" in head
        has_free = b"free" in tail or b"free" in head
        return has_moov and (has_mdat or has_free)
    except OSError:
        return False


def stop_screen_record(process: subprocess.Popen, remote_path: str, local_path: str | Path, timeout: int = 20) -> Path:
    """停止录屏并拉取 mp4 到本地。优先优雅结束 screenrecord，并等待远端文件稳定后再导出。"""
    if process.poll() is None:
        try:
            process.send_signal(subprocess.signal.SIGINT)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                run_adb(["shell", "pkill", "-2", "-f", f"screenrecord.*{Path(remote_path).name}"], timeout=6, check=False)
            except Exception:
                pass
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    remote_size = _wait_for_remote_recording_file_ready(remote_path, stop_timeout=min(timeout, 10))

    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    pull_result = None
    for _ in range(8):
        if local_path.exists():
            try:
                local_path.unlink()
            except OSError:
                pass
        pull_result = run_adb(["pull", remote_path, str(local_path)], timeout=max(timeout, 20), check=False)
        local_size = local_path.stat().st_size if local_path.exists() else 0
        if local_size > 0 and remote_size > 0 and local_size == remote_size:
            break
        if local_size > 0 and remote_size <= 0:
            break
        time.sleep(0.5)
        remote_size = _wait_for_remote_recording_file_ready(remote_path, stop_timeout=4)

    run_adb(["shell", "rm", "-f", remote_path], timeout=8, check=False)
    if local_path.exists() and local_path.stat().st_size > 0:
        final_local_size = local_path.stat().st_size
        if (remote_size <= 0 or final_local_size == remote_size) and _looks_like_complete_mp4(local_path):
            return local_path
    detail = pull_result.output_text if pull_result is not None else "未拉取到有效 mp4 文件"
    raise AdbCommandError(f"录屏文件导出失败或文件结构不完整：{detail}")


def trigger_system_screenshot() -> None:
    """尽量触发系统截图浮层。"""
    attempts = [
        ["shell", "cmd", "statusbar", "screenshot"],
        ["shell", "input", "keyevent", "120"],
    ]
    last_error = None
    for args in attempts:
        try:
            run_adb(args, timeout=8)
            time.sleep(1.0)
            return
        except Exception as exc:
            last_error = exc
    if last_error:
        raise AdbCommandError(f"无法触发系统截图：{format_adb_error(last_error)}")


def dump_ui_xml() -> str:
    """导出当前界面 UI XML。"""
    remote_path = f"/sdcard/window_dump_{uuid.uuid4().hex}.xml"
    try:
        result = run_adb(["shell", "uiautomator", "dump", remote_path], timeout=12, check=False)
        output = result.output_text.lower()
        if result.returncode != 0 and "dumped to" not in output:
            detail = result.output_text or f"返回码 {result.returncode}"
            raise AdbCommandError(f"uiautomator dump 失败：{detail}")
        xml_result = run_adb(["shell", "cat", remote_path], timeout=12)
        return xml_result.stdout_text
    finally:
        run_adb(["shell", "rm", "-f", remote_path], timeout=8, check=False)


def _parse_bounds_center(bounds: str) -> tuple[int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", (bounds or "").strip())
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def tap_screen(x: int, y: int) -> None:
    run_adb(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=8)


def find_ui_nodes_by_keywords(keywords: list[str]) -> list[dict]:
    """在当前 UI XML 中按文案/描述查找候选节点。"""
    xml_text = dump_ui_xml()
    root = ET.fromstring(xml_text)
    normalized = [item.strip().lower() for item in keywords if item and item.strip()]
    matches: list[dict] = []
    for node in root.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        resource_id = (node.attrib.get("resource-id") or "").strip()
        haystack = " ".join([text, desc, resource_id]).lower()
        if not haystack:
            continue
        hit = next((kw for kw in normalized if kw in haystack), None)
        if not hit:
            continue
        center = _parse_bounds_center(node.attrib.get("bounds", ""))
        if center is None:
            continue
        matches.append(
            {
                "keyword": hit,
                "text": text,
                "desc": desc,
                "resource_id": resource_id,
                "bounds": node.attrib.get("bounds", ""),
                "center": center,
                "clickable": node.attrib.get("clickable", "false") == "true",
            }
        )
    return matches


def try_tap_ui_keywords(keywords: list[str]) -> dict | None:
    """查找并点击指定关键词候选按钮。"""
    candidates = find_ui_nodes_by_keywords(keywords)
    if not candidates:
        return None

    def _score(item: dict) -> tuple[int, int, int]:
        text_len = len(item.get("text") or item.get("desc") or "")
        center = item.get("center") or (0, 0)
        return (0 if item.get("clickable") else 1, text_len, center[1])

    candidates.sort(key=_score)
    chosen = candidates[0]
    x, y = chosen["center"]
    tap_screen(x, y)
    time.sleep(0.8)
    return chosen


def list_remote_files(directory: str, glob_pattern: str = "*") -> list[str]:
    result = run_adb(["shell", "sh", "-c", f'ls -1t {directory}/{glob_pattern} 2>/dev/null || true'], timeout=12)
    files = []
    for line in result.stdout_text.splitlines():
        value = line.strip()
        if value:
            files.append(value)
    return files


def pull_remote_file(remote_path: str, local_path: str | Path, remove_remote: bool = False) -> Path:
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run_adb(["pull", remote_path, str(local_path)], timeout=60)
    if remove_remote:
        run_adb(["shell", "rm", "-f", remote_path], timeout=8, check=False)
    if not local_path.exists() or local_path.stat().st_size <= 0:
        raise AdbCommandError(f"文件拉取失败：{remote_path}")
    return local_path


def try_fetch_latest_system_screenshot(local_path: str | Path, created_after: float | None = None) -> Path:
    """从常见系统截图目录拉取最新截图。"""
    remote_dirs = [
        "/sdcard/Pictures/Screenshots",
        "/sdcard/DCIM/Screenshots",
        "/sdcard/DCIM/ScreenRecorder",
        "/sdcard/DCIM",
        "/sdcard/Pictures",
    ]
    candidates: list[str] = []
    for remote_dir in remote_dirs:
        candidates.extend(list_remote_files(remote_dir, "*.png"))
        candidates.extend(list_remote_files(remote_dir, "*.jpg"))
        candidates.extend(list_remote_files(remote_dir, "*.jpeg"))

    if not candidates:
        raise AdbCommandError("未在常见系统截图目录中发现截图文件")

    lowered_keywords = ["screenshot", "screen_shot", "screencapture", "截屏", "截图", "长截图", "滚动", "long"]
    preferred = [path for path in candidates if any(key in path.lower() for key in lowered_keywords)]
    ordered = preferred + [path for path in candidates if path not in preferred]

    checked: list[str] = []
    for remote_path in ordered:
        checked.append(remote_path)
        result = run_adb(["shell", "stat", "-c", "%Y %s", remote_path], timeout=8, check=False)
        parts = result.stdout_text.strip().split()
        if len(parts) >= 2:
            try:
                mtime = float(parts[0])
                size = int(parts[1])
            except ValueError:
                mtime = 0.0
                size = 0
            if created_after is not None and mtime + 1 < created_after:
                continue
            if size <= 0:
                continue
        return pull_remote_file(remote_path, local_path)

    raise AdbCommandError(f"找到截图文件但未命中新产物：{checked[:5]}")


def system_longshot_keywords() -> list[str]:
    return [
        "长截图", "滚动截图", "截长屏", "长截屏", "长屏截图", "捕获更多", "更多", "滚动", "长图",
        "scroll", "long screenshot", "scrollshot", "capture more", "extended screenshot", "longshot",
    ]


def _safe_fs_name(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", (text or "").strip())
    return value.strip("._") or "app"


def get_package_apk_paths(package: str) -> list[str]:
    """获取指定包名对应的 APK 路径（含 split APK）。"""
    package = package.strip()
    if not package:
        raise AdbCommandError("包名为空，无法导出 APK")

    result = run_adb(["shell", "pm", "path", package], timeout=15)
    remote_paths: list[str] = []
    for line in result.stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("package:"):
            remote_paths.append(line.split("package:", 1)[1].strip())
        else:
            remote_paths.append(line)

    remote_paths = [path for path in remote_paths if path]
    if not remote_paths:
        raise AdbCommandError(f"未找到 {package} 的 APK 路径")
    return remote_paths


def export_package_apks(package: str, output_dir: str | Path, app_name: str | None = None) -> list[Path]:
    """导出指定应用的 APK 文件；若存在 split APK，则全部导出到同一目录。"""
    remote_paths = get_package_apk_paths(package)
    label = (app_name or get_app_name(package) or package).strip()
    package_dir = Path(output_dir) / f"{_safe_fs_name(label)}_{_safe_fs_name(package)}"
    package_dir.mkdir(parents=True, exist_ok=True)

    exported_files: list[Path] = []
    multi_apk = len(remote_paths) > 1
    for index, remote_path in enumerate(remote_paths, start=1):
        remote_name = Path(remote_path).name or f"part_{index}.apk"
        remote_name = _safe_fs_name(remote_name)
        if not remote_name.lower().endswith(".apk"):
            remote_name += ".apk"

        if multi_apk:
            local_name = remote_name
        else:
            local_name = f"{_safe_fs_name(label)}_{_safe_fs_name(package)}.apk"

        local_path = package_dir / local_name
        run_adb(["pull", remote_path, str(local_path)], timeout=60)
        if not local_path.exists() or local_path.stat().st_size <= 0:
            raise AdbCommandError(f"APK 导出失败：{package} -> {remote_path}")
        exported_files.append(local_path)

    return exported_files


def uninstall_app(package: str, keep_data: bool = False) -> bool:
    """卸载 App；默认同时删除数据"""
    args = ["shell", "pm", "uninstall"]
    if keep_data:
        args.append("-k")
    args.append(package)
    result = run_adb(args, timeout=25, check=False)
    output = (result.stdout_text + result.stderr_text).lower()
    if "unauthorized" in output:
        raise AdbUnauthorizedError("设备未授权，无法执行卸载")
    if any(token in output for token in ["device offline", "no devices/emulators found"]):
        raise AdbNoDeviceError("设备不可用，无法执行卸载")
    if result.returncode == 0 and "success" in output:
        return True
    if result.returncode != 0:
        detail = result.output_text or f"返回码 {result.returncode}"
        raise AdbCommandError(f"卸载失败：{detail}")
    return False


def format_adb_error(exc: Exception) -> str:
    if isinstance(exc, AdbUnauthorizedError):
        return f"ADB 未授权：{exc}"
    if isinstance(exc, AdbNoDeviceError):
        return f"ADB 无可用设备：{exc}"
    if isinstance(exc, AdbTimeoutError):
        return f"ADB 执行超时：{exc}"
    if isinstance(exc, AdbNotFoundError):
        return f"ADB 未安装：{exc}"
    if isinstance(exc, AdbCommandError):
        return f"ADB 命令失败：{exc}"
    if isinstance(exc, AdbError):
        return f"ADB 异常：{exc}"
    return str(exc)


def safe_check_device() -> tuple[bool, str]:
    try:
        return True, check_device()
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_screen_resolution() -> tuple[bool, tuple[int, int] | str]:
    try:
        return True, get_screen_resolution()
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_device_profile() -> tuple[bool, dict | str]:
    try:
        return True, get_device_profile()
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_current_app() -> tuple[bool, dict | str]:
    try:
        return True, get_current_app()
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_list_installed_apps(include_system: bool = True) -> tuple[bool, list[dict] | str]:
    try:
        return True, list_installed_apps(include_system=include_system)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_export_package_apks(package: str, output_dir: str | Path, app_name: str | None = None) -> tuple[bool, list[Path] | str]:
    try:
        return True, export_package_apks(package, output_dir=output_dir, app_name=app_name)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_uninstall_app(package: str, keep_data: bool = False) -> tuple[bool, bool | str]:
    try:
        return True, uninstall_app(package, keep_data=keep_data)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_take_screenshot() -> tuple[bool, bytes | str]:
    try:
        data = take_screenshot()
        if not data:
            return False, "截图为空"
        return True, data
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_chat_title() -> tuple[bool, str]:
    try:
        return True, get_chat_title()
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_install_source(package: str) -> tuple[bool, str]:
    try:
        return True, get_install_source(package)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_run_adb(args: list, timeout: int = 10, check: bool = True) -> tuple[bool, AdbResult | str]:
    try:
        return True, run_adb(args, timeout=timeout, check=check)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_start_screen_record(remote_path: str = "/sdcard/Download/0xsec_record.mp4", bit_rate: int = 8000000) -> tuple[bool, tuple[subprocess.Popen, str] | str]:
    try:
        return True, start_screen_record(remote_path=remote_path, bit_rate=bit_rate)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_stop_screen_record(process: subprocess.Popen, remote_path: str, local_path: str | Path, timeout: int = 20) -> tuple[bool, Path | str]:
    try:
        return True, stop_screen_record(process, remote_path, local_path, timeout=timeout)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_get_app_name(package: str) -> tuple[bool, str]:
    try:
        return True, get_app_name(package)
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_image_similarity(img_a: bytes, img_b: bytes, crop: bool = True) -> tuple[bool, float | str]:
    try:
        return True, image_similarity(img_a, img_b, crop=crop)
    except Exception as exc:
        return False, str(exc)


def safe_screenshot_hash(img_bytes: bytes) -> tuple[bool, str]:
    try:
        return True, screenshot_hash(img_bytes)
    except Exception as exc:
        return False, str(exc)


def safe_swipe_up(start_x=None, start_y=None, end_x=None, end_y=None, duration: int = 450) -> tuple[bool, str]:
    try:
        swipe_up(start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y, duration=duration)
        return True, "ok"
    except Exception as exc:
        return False, format_adb_error(exc)


def safe_swipe_down(start_x=None, start_y=None, end_x=None, end_y=None, duration: int = 450) -> tuple[bool, str]:
    try:
        swipe_down(start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y, duration=duration)
        return True, "ok"
    except Exception as exc:
        return False, format_adb_error(exc)


_BLOCKED_TITLES = {
    "",
    " ",
    "返回",
    "更多",
    "···",
    "⋮",
    "搜索",
    "聊天信息",
    "群公告",
    "联系人",
    "消息",
    "发现",
    "我",
    "首页",
    "取消",
    "完成",
    "确定",
    "发送",
    "选择",
    "编辑",
    "语音通话",
    "视频通话",
    "拨号",
    "拍照",
    "相册",
    "表情",
    "加号",
    "+",
}

_TITLE_ID_KEYWORDS = (
    "title",
    "toolbar",
    "actionbar",
    "header",
    "conversation",
    "chat",
    "nickname",
    "nick_name",
    "display_name",
    "name",
    "center",
    "middle",
)

_NEGATIVE_TITLE_HINTS = (
    "搜索",
    "取消",
    "发送",
    "更多",
    "表情",
    "拍照",
    "语音",
    "视频",
    "输入",
    "按住",
    "说话",
    "未读",
    "在线",
    "刚刚",
)


def _parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def _extract_xml_root(output: str) -> ET.Element | None:
    start = output.find("<hierarchy")
    if start < 0:
        start = output.find("<?xml")
    if start < 0:
        return None
    xml_text = output[start:].strip()
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        return None


def _clean_title_text(text: str) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    value = value.strip("-—_·•|:：")
    value = re.sub(r"^\(?\d+\)?\s*条?新消息\s*", "", value)
    return value.strip()


def _looks_like_title(text: str) -> bool:
    stripped = _clean_title_text(text)
    if not stripped:
        return False
    if stripped in _BLOCKED_TITLES:
        return False
    if len(stripped) > 60:
        return False
    if stripped.isdigit():
        return False
    if re.fullmatch(r"[\d\W_]+", stripped):
        return False
    if re.search(r"\b(AM|PM)\b", stripped, re.IGNORECASE):
        return False
    if re.search(r"^\d{1,2}:\d{2}$", stripped):
        return False
    return True


def _is_probable_message_snippet(text: str) -> bool:
    stripped = _clean_title_text(text)
    if not stripped:
        return True
    if len(stripped) >= 28:
        return True
    if any(token in stripped for token in ["：", ":", "http://", "https://", "[图片]", "[表情]", "撤回", "邀请", "加入群聊"]):
        return True
    if re.search(r"\d{1,2}:\d{2}", stripped):
        return True
    return False


def _score_title_candidate(
    text: str,
    resource_id: str,
    node_class: str,
    bounds: str,
    screen_width: int,
    screen_height: int,
) -> int:
    cleaned = _clean_title_text(text)
    if not _looks_like_title(cleaned):
        return -999

    score = 0
    lower_id = (resource_id or "").lower()
    lower_class = (node_class or "").lower()
    lower_text = cleaned.lower()

    if any(key in lower_id for key in _TITLE_ID_KEYWORDS):
        score += 14
    if any(key in lower_class for key in ("textview", "toolbar", "actionbar")):
        score += 3
    if len(cleaned) <= 18:
        score += 5
    elif len(cleaned) <= 32:
        score += 3
    elif len(cleaned) <= 48:
        score += 1
    if re.search(r"[\u4e00-\u9fffA-Za-z]", cleaned):
        score += 3
    if any(token.lower() in lower_text for token in _NEGATIVE_TITLE_HINTS):
        score -= 8
    if _is_probable_message_snippet(cleaned):
        score -= 12

    parsed = _parse_bounds(bounds)
    if parsed:
        left, top, right, bottom = parsed
        width = max(screen_width, 1)
        height = max(screen_height, 1)
        node_width = max(1, right - left)
        node_height = max(1, bottom - top)
        center_x = (left + right) / 2
        center_bias = abs(center_x - (width / 2)) / width

        if top <= height * 0.18:
            score += 12
        elif top <= height * 0.24:
            score += 8
        elif top <= height * 0.32:
            score += 3
        else:
            score -= 10

        if bottom <= height * 0.22:
            score += 7
        elif bottom <= height * 0.30:
            score += 3
        elif bottom > height * 0.42:
            score -= 10

        width_ratio = node_width / width
        height_ratio = node_height / height
        if 0.18 <= width_ratio <= 0.75:
            score += 6
        elif width_ratio < 0.10:
            score -= 6
        elif width_ratio > 0.90:
            score -= 8

        if 0.018 <= height_ratio <= 0.10:
            score += 2

        if center_bias <= 0.08:
            score += 8
        elif center_bias <= 0.16:
            score += 4
        elif center_bias >= 0.30:
            score -= 6

    if cleaned.startswith(("微信", "QQ", "群聊", "讨论组")):
        score += 2

    return score


def _collect_title_candidates(root: ET.Element, screen_width: int, screen_height: int) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    seen: set[tuple[str, str]] = set()
    for node in root.iter("node"):
        texts = [
            (node.attrib.get("text") or "").strip(),
            (node.attrib.get("content-desc") or "").strip(),
        ]
        resource_id = node.attrib.get("resource-id", "")
        node_class = node.attrib.get("class", "")
        bounds = node.attrib.get("bounds", "")
        for raw_text in texts:
            cleaned = _clean_title_text(raw_text)
            if not cleaned:
                continue
            key = (cleaned, bounds)
            if key in seen:
                continue
            seen.add(key)
            score = _score_title_candidate(cleaned, resource_id, node_class, bounds, screen_width, screen_height)
            if score > -999:
                candidates.append((score, cleaned))
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates


def _get_window_focus_title() -> str:
    result = run_adb(["shell", "dumpsys", "window"], timeout=20)
    output = result.stdout.decode(errors="ignore")
    patterns = [
        r"mCurrentFocus.*?\s([A-Za-z0-9_.]+)/(?:[A-Za-z0-9_.$]+)",
        r"mFocusedApp.*?\s([A-Za-z0-9_.]+)/",
        r"topResumedActivity.*?\s([A-Za-z0-9_.]+)/",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return ""


def get_chat_title() -> str:
    """尝试获取当前聊天页面标题（优先顶部工具栏候选，其次窗口焦点与文本回退）"""
    screen_width, screen_height = get_screen_resolution()

    xml_output = ""
    try:
        xml_output = dump_ui_xml()
    except Exception:
        result = run_adb(["shell", "uiautomator", "dump", "/dev/tty"], timeout=20)
        xml_output = result.stdout.decode(errors="ignore")

    root = _extract_xml_root(xml_output)
    if root is not None:
        candidates = _collect_title_candidates(root, screen_width, screen_height)
        if candidates:
            best_score, best_text = candidates[0]
            if best_score >= 8:
                return best_text
            short_top_candidates = [text for score, text in candidates[:5] if score >= 2 and len(text) <= 24]
            if short_top_candidates:
                return short_top_candidates[0]

    focus_title = _clean_title_text(_get_window_focus_title())
    if focus_title and focus_title not in _BLOCKED_TITLES:
        return focus_title.split(".")[-1] if "/" not in focus_title else focus_title

    text_candidates: list[str] = []
    for match in re.finditer(r'text="([^"]+)"', xml_output):
        text = _clean_title_text(match.group(1))
        if _looks_like_title(text) and not _is_probable_message_snippet(text):
            text_candidates.append(text)

    if text_candidates:
        text_candidates.sort(key=lambda item: (len(item) > 24, len(item)))
        return text_candidates[0]

    return ""


def take_screenshot() -> bytes | None:
    """截取当前屏幕，返回 PNG 字节"""
    result = run_adb(["exec-out", "screencap", "-p"], timeout=8)
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return None


def _prepare_image(img_bytes: bytes, crop: bool = True, size: tuple[int, int] = (64, 64)) -> Image.Image:
    img = Image.open(BytesIO(img_bytes)).convert("L")
    if crop:
        width, height = img.size
        top = int(height * 0.07)
        bottom = int(height * 0.10)
        if height - top - bottom > 32:
            img = img.crop((0, top, width, height - bottom))
    return img.resize(size)


def estimate_vertical_shift(img_a: bytes, img_b: bytes, crop: bool = True, size: tuple[int, int] = (72, 96)) -> float:
    """估算两张截图之间的垂直位移比例。

    返回值是归一化后的位移强度，范围约为 0..1，数值越小表示页面越没有发生滚动。
    这个方法只依赖 PIL，不受动图局部帧变化影响太大，适合做触底/触顶的“无位移”判定。
    """
    a = _prepare_image(img_a, crop=crop, size=size)
    b = _prepare_image(img_b, crop=crop, size=size)
    width, height = a.size
    if width <= 0 or height <= 0:
        return 1.0

    max_shift = max(2, min(height // 4, 12))
    best_shift = 0
    best_score = None

    for shift in range(-max_shift, max_shift + 1):
        if shift >= 0:
            a_box = (0, 0, width, height - shift)
            b_box = (0, shift, width, height)
        else:
            offset = -shift
            a_box = (0, offset, width, height)
            b_box = (0, 0, width, height - offset)

        if a_box[2] <= a_box[0] or a_box[3] <= a_box[1]:
            continue

        diff = ImageChops.difference(a.crop(a_box), b.crop(b_box))
        stat = ImageStat.Stat(diff)
        score = stat.mean[0] if stat.mean else 255.0

        if best_score is None or score < best_score:
            best_score = score
            best_shift = shift

    return min(1.0, abs(best_shift) / max(1, height))


def image_similarity(img_a: bytes, img_b: bytes, crop: bool = True) -> float:
    """计算两张截图的相似度，返回 0~1"""
    a = _prepare_image(img_a, crop=crop)
    b = _prepare_image(img_b, crop=crop)
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    mean = stat.mean[0] if stat.mean else 255.0
    return max(0.0, min(1.0, 1.0 - (mean / 255.0)))


def screenshot_hash(img_bytes: bytes) -> str:
    """兼容旧接口：返回内容摘要（不再依赖全图 MD5）"""
    import hashlib

    prepared = _prepare_image(img_bytes, crop=True, size=(32, 32))
    return hashlib.md5(prepared.tobytes()).hexdigest()


def get_swipe_coordinates(width: int, height: int, direction: str = "up") -> tuple[int, int, int, int]:
    """按分辨率生成滑动坐标"""
    center_x = int(width * 0.5)
    up_start_y = int(height * 0.78)
    up_end_y = int(height * 0.28)
    down_start_y = int(height * 0.28)
    down_end_y = int(height * 0.78)

    if direction == "down":
        return center_x, down_start_y, center_x, down_end_y
    return center_x, up_start_y, center_x, up_end_y


def swipe_up(start_x=None, start_y=None, end_x=None, end_y=None, duration: int = 450):
    """向上滑动手势（手指从下往上），常用于查看更新消息"""
    if None in (start_x, start_y, end_x, end_y):
        width, height = get_screen_resolution()
        start_x, start_y, end_x, end_y = get_swipe_coordinates(width, height, "up")
    run_adb([
        "shell", "input", "swipe",
        str(start_x), str(start_y),
        str(end_x), str(end_y),
        str(duration),
    ])


def swipe_down(start_x=None, start_y=None, end_x=None, end_y=None, duration: int = 450):
    """向下滑动手势（手指从上往下），常用于返回更早消息/聊天顶部"""
    if None in (start_x, start_y, end_x, end_y):
        width, height = get_screen_resolution()
        start_x, start_y, end_x, end_y = get_swipe_coordinates(width, height, "down")
    run_adb([
        "shell", "input", "swipe",
        str(start_x), str(start_y),
        str(end_x), str(end_y),
        str(duration),
    ])
