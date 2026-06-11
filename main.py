"""ChatExtractor-Screenshot 主程序 - PySide6 GUI + CLI 回退"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from config import CONFIG
from adb_utils import (
    format_adb_error,
    safe_check_device,
    safe_export_package_apks,
    safe_get_chat_title,
    safe_get_current_app,
    safe_get_device_profile,
    safe_get_screen_resolution,
    safe_list_installed_apps,
    safe_uninstall_app,
)
from capture import ScreenCapture

MIN_PYTHON = (3, 10)
QT_BINDING = None
QT_AVAILABLE = False
QT_IMPORT_ERROR = ""

try:
    from PySide6.QtCore import QObject, QTimer, Qt, Signal, QUrl
    from PySide6.QtGui import QDesktopServices, QTextCursor, QPainter, QPen, QColor, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QSizePolicy,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    QT_BINDING = "PySide6"
    QT_AVAILABLE = True
except Exception as exc:
    QT_IMPORT_ERROR = f"PySide6 导入失败: {exc}"
    try:
        from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal as Signal, QUrl
        from PyQt5.QtGui import QDesktopServices, QTextCursor, QPainter, QPen, QColor, QPixmap
        from PyQt5.QtWidgets import (
            QApplication,
            QAbstractItemView,
            QCheckBox,
            QComboBox,
            QDialog,
            QFileDialog,
            QFrame,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QHeaderView,
            QInputDialog,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QRadioButton,
            QScrollArea,
            QSizePolicy,
            QStatusBar,
            QTabWidget,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
        QT_BINDING = "PyQt5"
        QT_AVAILABLE = True
    except Exception as exc:
        QT_AVAILABLE = False
        QT_BINDING = None
        if QT_IMPORT_ERROR:
            QT_IMPORT_ERROR += f" | PyQt5 导入失败: {exc}"
        else:
            QT_IMPORT_ERROR = f"PyQt5 导入失败: {exc}"


def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def print_banner():
    print("=" * 64)
    print("  ChatExtractor-Screenshot Version")
    print("  聊天截图采集工具")
    print("=" * 64)


def sanitize_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in text).strip().replace(" ", "_")


GUI_STATE_PATH = Path(__file__).resolve().parent / ".gui_state.json"


def load_gui_state() -> dict:
    try:
        if GUI_STATE_PATH.exists():
            return json.loads(GUI_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_gui_state(state: dict):
    try:
        GUI_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def confirm_input(prompt: str, default: str = "") -> str:
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    return input(f"{prompt}: ").strip()


def setup_project() -> tuple[Path, str, str]:
    print("\n检查设备连接...")
    ok_device, device_or_error = safe_check_device()
    if not ok_device:
        print(f"{device_or_error}")
        sys.exit(1)
    device_id = str(device_or_error)
    print(f"设备已连接: {device_id}")

    ok_res, resolution_or_error = safe_get_screen_resolution()
    if not ok_res:
        print(f"{resolution_or_error}")
        sys.exit(1)
    w, h = resolution_or_error
    print(f"屏幕分辨率: {w}x{h}")

    print("\n识别当前 App...")
    ok_app, app_or_error = safe_get_current_app()
    if not ok_app:
        print(f"{app_or_error}")
        sys.exit(1)
    app_info = app_or_error
    package = app_info["package"]
    app_name = app_info["app_name"]

    print(f"   App名称: {app_name}")
    print(f"   包名: {package}")

    confirmed_name = confirm_input("\n确认 App 名称（回车确认，或输入修改）", app_name)
    project_name = sanitize_name(f"{confirmed_name}_{package}")
    project_dir = Path(CONFIG["output_root"]) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "logs").mkdir(exist_ok=True)

    print(f"\n项目目录: {project_dir}")
    return project_dir, confirmed_name, package


def start_chat_capture(project_dir: Path, capturer: ScreenCapture):
    print("\n" + "-" * 60)
    print("   请先在手机上打开目标聊天页面")
    input("   准备好后按回车继续...")

    print("\n尝试识别聊天标题...")
    ok_title, title_or_error = safe_get_chat_title()
    auto_title = str(title_or_error).strip() if ok_title else ""

    if auto_title:
        print(f"   检测到标题: {auto_title}")
        chat_title = confirm_input("确认聊天标题（回车确认，或输入修改）", auto_title)
    else:
        print("   未能自动识别标题")
        if not ok_title:
            print(f"   原因: {title_or_error}")
        chat_title = confirm_input("请输入聊天标题（对方昵称/群名）")

    if not chat_title:
        print("标题不能为空")
        return

    safe_title = sanitize_name(chat_title)
    print(f"\n 即将开始截图: {safe_title}")
    print(f"   保存位置: {project_dir / safe_title}/")
    print(f"   最大截图数: {CONFIG['max_screenshots']}")
    print(f"   滚动间隔: {CONFIG['swipe_interval']} 秒")
    print()
    print("   模式：先找顶部，再从顶部向下记录")
    input("   按回车开始...")

    count = capturer.auto_capture_with_scroll(safe_title, mode="down")
    log_file = project_dir / "logs" / "capture_log.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 聊天: {safe_title}, 截图数: {count}\n")


def start_important_capture(project_dir: Path, capturer: ScreenCapture):
    print("\n" + "-" * 60)
    print("  重点内容截图模式")
    print("   自动识别 APK / 链接 / 账号等重要信息，只保存相关上下文")
    input("   请先在手机上打开目标聊天页面，准备好后按回车继续...")

    ok_title, title_or_error = safe_get_chat_title()
    auto_title = str(title_or_error).strip() if ok_title else ""

    if auto_title:
        print(f"   检测到标题: {auto_title}")
        chat_title = confirm_input("确认聊天标题（回车确认，或输入修改）", auto_title)
    else:
        print("   未能自动识别标题")
        if not ok_title:
            print(f"   原因: {title_or_error}")
        chat_title = confirm_input("请输入聊天标题（对方昵称/群名）")

    if not chat_title:
        print("标题不能为空")
        return

    safe_title = sanitize_name(chat_title)
    print(f"\n即将开始重点内容截图: {safe_title}")
    print(f"   保存位置: {project_dir / safe_title / 'important'}/")
    print(f"   最大截图数: {CONFIG['max_screenshots']}")
    print(f"   滚动间隔: {CONFIG['swipe_interval']} 秒")
    print()
    print("   模式：自动识别 APK / 链接 / 账号并裁取上下文")
    input("   按回车开始...")

    try:
        count, output_path = capturer.important_capture_and_crop(safe_title, stop_event=None)
    except Exception as exc:
        print(f"重点内容截图失败：{exc}")
        return
    log_file = project_dir / "logs" / "capture_log.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 重点内容聊天: {safe_title}, 截图数: {count}, 输出: {output_path}\n")


def manual_capture_mode(capturer: ScreenCapture):
    print("\n" + "-" * 40)
    print("手动截图模式")
    print("   输入文件名后截图，输入 q 退出\n")

    while True:
        name = input("文件名（留空自动命名，q退出）: ").strip()
        if name.lower() == "q":
            break
        capturer.manual_capture(name if name else None)


def show_project_files(project_dir: Path):
    print(f"\n项目目录: {project_dir}\n")

    chat_folders = []
    manual_count = 0

    for item in sorted(project_dir.iterdir()):
        if item.is_dir() and item.name not in ("logs", "手动截图"):
            count = len(list(item.glob("*.png")))
            chat_folders.append((item.name, count))
        elif item.is_dir() and item.name == "手动截图":
            manual_count = len(list(item.glob("*.png")))

    if chat_folders:
        print("   聊天记录:")
        for name, count in chat_folders:
            print(f"      {name}: {count} 张")

    if manual_count > 0:
        print(f"\n   手动截图: {manual_count} 张")

    total = sum(c for _, c in chat_folders) + manual_count
    print(f"\n   总计: {total} 张截图")


def edit_config():
    print("\n当前配置:")
    for key in (
        "swipe_duration",
        "swipe_interval",
        "top_swipe_duration",
        "top_swipe_rounds",
        "top_stable_threshold",
        "max_screenshots",
        "duplicate_threshold",
        "similarity_threshold",
        "top_detection_threshold",
        "bottom_motion_threshold",
        "bottom_motion_threshold_hits",
    ):
        print(f"   {key}: {CONFIG[key]}")
    print()

    for key, caster in (
        ("swipe_duration", int),
        ("swipe_interval", float),
        ("top_swipe_duration", int),
        ("top_swipe_rounds", int),
        ("top_stable_threshold", int),
        ("max_screenshots", int),
        ("duplicate_threshold", int),
        ("similarity_threshold", float),
        ("top_detection_threshold", float),
        ("bottom_motion_threshold", float),
        ("bottom_motion_threshold_hits", int),
    ):
        val = input(f"{key}（回车跳过）: ").strip()
        if val:
            CONFIG[key] = caster(val)

    print("配置已更新（本次运行有效）")


def main_menu(project_dir: Path, capturer: ScreenCapture):
    while True:
        print("\n" + "=" * 42)
        print("  📱 主菜单")
        print("=" * 42)
        print("  1. 自动录制聊天记录（先找顶部）")
        print("  2. 手动截图（单张）")
        print("  3. 手动录屏（不自动滑动）")
        print("  4. 重点内容截图（APK / 链接 / 账号）")
        print("  5. 当前界面向上自动滑动录屏")
        print("  6. 查看项目文件")
        print("  7. 修改配置")
        print("  8. 退出")
        print()

        choice = input("选择操作 [1-8]: ").strip()
        if choice == "1":
            start_chat_capture(project_dir, capturer)
        elif choice == "2":
            manual_capture_mode(capturer)
        elif choice == "3":
            session_name = confirm_input("录屏名称", f"manual_record_{datetime.now():%Y%m%d_%H%M%S}")
            capturer.record_session(sanitize_name(session_name), auto_swipe=False)
        elif choice == "4":
            start_important_capture(project_dir, capturer)
        elif choice == "5":
            session_name = confirm_input("录屏名称", f"swipe_up_{datetime.now():%Y%m%d_%H%M%S}")
            capturer.record_session(sanitize_name(session_name), auto_swipe=True, swipe_direction="up")
        elif choice == "6":
            show_project_files(project_dir)
        elif choice == "7":
            edit_config()
        elif choice == "8":
            print("\n再见！")
            break
        else:
            print("无效选择")


if QT_AVAILABLE:
    class UiBridge(QObject):
        log_signal = Signal(str)
        status_signal = Signal(str)
        task_state_signal = Signal(str, str)
        device_detected_signal = Signal(dict, bool, str, bool)
        app_detected_signal = Signal(dict, bool, str, bool, bool)
        app_list_signal = Signal(list)
        app_error_signal = Signal(str)
        app_refresh_done_signal = Signal()
        uninstall_success_signal = Signal(str, str)
        uninstall_fail_signal = Signal(str, str)
        uninstall_error_signal = Signal(str, str)
        apk_export_success_signal = Signal(list, list)
        apk_export_error_signal = Signal(str)
        apk_export_done_signal = Signal()
        resource_found_signal = Signal(dict, str)  # result_dict, folder_path
        resource_scan_empty_signal = Signal(str)


    @dataclass
    class FieldBundle:
        device: QLineEdit
        app_name: QLineEdit
        package: QLineEdit
        chat_title: QLineEdit
        project_root: QLineEdit
        session_name: QLineEdit
        custom_name_checkbox: QCheckBox | None = None


    class CaptureMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("自动截屏工具")
            self.resize(1320, 920)
            self.setMinimumSize(1160, 840)
            self.gui_state = load_gui_state()
            self.theme_mode = "light"
            self._base_stylesheet = ""

            self.stop_event = threading.Event()
            self.worker: threading.Thread | None = None
            self.project_dir: Path | None = None
            self.capturer: ScreenCapture | None = None
            self.capture_project_dir: Path | None = None
            self.record_project_dir: Path | None = None
            self.longshot_project_dir: Path | None = None
            self.app_project_dir: Path | None = None
            self.capture_capturer: ScreenCapture | None = None
            self.record_capturer: ScreenCapture | None = None
            self.longshot_capturer: ScreenCapture | None = None
            self.current_context_kind = "capture"
            self.current_task_kind = "idle"
            self.current_task_state = "idle"

            self.app_items: list[dict] = []
            self.app_page = 0
            self.app_page_size = 10
            self.app_filter_text = ""
            self.app_selected_packages: set[str] = set()
            self.app_refreshing = False
            self.app_exporting = False
            self.runtime_log_buffer: list[str] = []
            self.device_info: dict = {}
            self.app_info: dict = {}
            self._last_auto_app_package = ""
            self._auto_detect_device_running = False
            self._auto_detect_app_running = False
            self._auto_detect_pending = False
            self._last_auto_detect_context = ""
            self._last_scheduled_auto_detect_context = ""
            self._last_project_signature_by_mode: dict[str, str] = {}
            self._last_log_message = ""

            self.bridge = UiBridge()
            self.bridge.log_signal.connect(self._append_log_ui)
            self.bridge.status_signal.connect(self._set_status_ui)
            self.bridge.task_state_signal.connect(self._apply_task_state_ui)
            self.bridge.device_detected_signal.connect(self._apply_detected_device_result)
            self.bridge.app_detected_signal.connect(self._apply_detected_app_result)
            self.bridge.app_list_signal.connect(self._apply_app_list)
            self.bridge.app_error_signal.connect(self._on_app_list_error)
            self.bridge.app_refresh_done_signal.connect(self._finish_app_refresh)
            self.bridge.apk_export_success_signal.connect(self._after_apk_export_success)
            self.bridge.apk_export_error_signal.connect(self._after_apk_export_error)
            self.bridge.apk_export_done_signal.connect(self._finish_apk_export)
            self.bridge.resource_found_signal.connect(self._show_resource_found_dialog)
            self.bridge.resource_scan_empty_signal.connect(self._show_resource_empty_dialog)

            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self.status_bar.showMessage("就绪")

            self.auto_detect_timer = QTimer(self)
            self.auto_detect_timer.setSingleShot(True)
            self.auto_detect_timer.setInterval(800)
            self.auto_detect_timer.timeout.connect(self._run_auto_detect_context)

            self._build_ui()
            self._apply_styles()
            self._append_log(f"欢迎使用 ChatExtractor-Screenshot · 0xSec · {QT_BINDING}")
            self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            QTimer.singleShot(50, self.detect_device)

        def _build_ui(self):
            central = QWidget()
            root = QVBoxLayout(central)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            header = QFrame()
            header.setObjectName("Header")
            header_layout = QVBoxLayout(header)
            header_layout.setContentsMargins(24, 20, 24, 18)
            header_layout.setSpacing(8)

            top_row = QHBoxLayout()
            top_row.setSpacing(14)

            brand_block = QVBoxLayout()
            brand_block.setSpacing(2)

            title = QLabel("自动截屏工具")
            title.setObjectName("HeaderTitle")
            subtitle = QLabel("截图 / 录屏 / 长截图 / App 导出")
            subtitle.setObjectName("HeaderSubtitle")
            brand_block.addWidget(title)
            brand_block.addWidget(subtitle)

            tags_row = QHBoxLayout()
            tags_row.setSpacing(8)
            for tag_text in ("纯本地处理", "轻量界面", "ADB 驱动"):
                tag = QLabel(tag_text)
                tag.setObjectName("HeaderTag")
                tags_row.addWidget(tag)

            self.header_status_badge = QLabel("就绪")
            self.header_status_badge.setObjectName("HeaderStatusBadge")

            left_column = QVBoxLayout()
            left_column.setSpacing(10)
            left_column.addLayout(brand_block)
            left_column.addLayout(tags_row)

            top_row.addLayout(left_column, 1)
            top_row.addStretch(1)
            top_row.addWidget(self.header_status_badge)
            header_layout.addLayout(top_row)
            root.addWidget(header)

            self.tabs = QTabWidget()
            self.tabs.setObjectName("MainTabs")
            self.tabs.setDocumentMode(True)
            try:
                self.tabs.tabBar().setDrawBase(False)
                self.tabs.tabBar().setExpanding(False)
            except Exception:
                pass
            self.tabs.currentChanged.connect(self._on_tab_changed)
            root.addWidget(self.tabs)

            self.capture_page = self._make_scroll_page()
            self.record_page = self._make_scroll_page()
            self.longshot_page = self._make_scroll_page()
            self.app_page_widget = self._make_scroll_page()
            self.log_page = self._make_scroll_page()
            self.capture_page[1].setObjectName("CapturePage")
            self.record_page[1].setObjectName("RecordPage")
            self.longshot_page[1].setObjectName("LongshotPage")
            self.app_page_widget[1].setObjectName("AppPage")
            self.log_page[1].setObjectName("LogPage")

            self.tabs.addTab(self.capture_page[0], "截图模式")
            self.tabs.addTab(self.record_page[0], "录屏模式")
            self.tabs.addTab(self.longshot_page[0], "长截图")
            self.tabs.addTab(self.app_page_widget[0], "App 导出")
            self.tabs.addTab(self.log_page[0], "运行日志")

            self.capture_fields = self._build_shared_panel(self.capture_page[1], mode_kind="capture")
            self.record_fields = self._build_shared_panel(self.record_page[1], mode_kind="record")
            self.longshot_fields = self._build_shared_panel(self.longshot_page[1], mode_kind="longshot")
            self._build_app_panel(self.app_page_widget[1])
            self._build_log_panel(self.log_page[1])

            self.setCentralWidget(central)

        def _theme_stylesheet(self) -> str:
            if self.theme_mode == "dark":
                return """
                QMainWindow { background: #0b1220; }
                #Header {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #020617, stop:1 #172554);
                    border-bottom: 1px solid rgba(148, 163, 184, 0.16);
                }
                #HeaderTitle { color: #f8fafc; font-size: 30px; font-weight: 800; letter-spacing: 0.4px; }
                #HeaderSubtitle { color: #93c5fd; font-size: 13px; }
                #HeaderTag {
                    color: #dbeafe; background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(148, 163, 184, 0.18);
                    border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700;
                }
                #HeaderStatusBadge {
                    color: #dcfce7; background: rgba(6, 95, 70, 0.42); border: 1px solid rgba(110, 231, 183, 0.35);
                    border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;
                }
                QTabWidget::pane { border: 0; background: #0b1220; }
                QTabBar::tab {
                    background: #1e293b; color: #e2e8f0; padding: 12px 20px; margin: 8px 6px 0 0;
                    border: 1px solid rgba(148, 163, 184, 0.12); border-bottom: 0; border-top-left-radius: 12px; border-top-right-radius: 12px; font-weight: 700;
                }
                QTabBar::tab:selected { background: #111827; }
                QTabBar::tab:hover:!selected { background: #243244; }
                QScrollArea { border: 0; background: #0b1220; }
                QGroupBox {
                    background: #111827; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 16px;
                    margin-top: 16px; font-weight: 700; color: #bfdbfe;
                }
                QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; }
                QLabel { color: #e5eefc; }
                QRadioButton, QCheckBox { color: #e5eefc; background: transparent; spacing: 8px; }
                QLineEdit, QComboBox, QTextEdit, QTableWidget {
                    background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 8px; color: #e2e8f0;
                }
                QComboBox QAbstractItemView {
                    background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
                    selection-background-color: #1d4ed8; selection-color: #ffffff; outline: 0;
                }
                QComboBox QAbstractItemView::item { padding: 6px 10px; }
                QTextEdit#LogConsole {
                    background: #020617; color: #67e8f9; border: 1px solid #1d4ed8; border-radius: 12px;
                    selection-background-color: #2563eb; font-family: 'JetBrains Mono'; font-size: 12px;
                }
                QPushButton {
                    border: 0; border-radius: 12px; padding: 10px 14px; background: #1e3a8a; color: #eff6ff; font-weight: 700;
                }
                QPushButton:hover { background: #1d4ed8; }
                QPushButton[role='primary'] { background: #2563eb; color: white; }
                QPushButton[role='primary']:hover { background: #1d4ed8; }
                QPushButton[role='danger'] { background: #dc2626; color: white; }
                QPushButton[role='danger']:hover { background: #b91c1c; }
                QPushButton[role='accent'] { background: #0f766e; color: white; }
                QPushButton[role='accent']:hover { background: #0d9488; }
                QPushButton[role='ghost'] { background: #0f172a; color: #93c5fd; border: 1px solid #334155; }
                QPushButton[role='ghost']:hover { background: #1e293b; }
                QHeaderView::section {
                    background: #1e3a8a; color: white; padding: 9px; border: 0; font-weight: 700;
                }
               QRadioButton, QCheckBox { background: transparent; }
               QRadioButton::indicator, QCheckBox::indicator {
                   width: 18px; height: 18px; border-radius: 9px;
                   border: 1px solid transparent; background: rgba(15, 23, 42, 0.02);
               }
               QCheckBox::indicator { border-radius: 6px; }
               QRadioButton::indicator:hover, QCheckBox::indicator:hover {
                   border: 1px solid rgba(148, 163, 184, 0.05); background: rgba(30, 41, 59, 0.06);
               }
               QRadioButton::indicator:checked, QCheckBox::indicator:checked {
                   border: 1px solid rgba(0, 0, 0, 0.3); background: rgba(0, 0, 0, 0.8);
               }
                QTableWidget { gridline-color: #334155; alternate-background-color: #172033; }
                QStatusBar { background: #111827; color: #93c5fd; font-weight: 700; }
                """
            if self.theme_mode == "light":
                return """
                QMainWindow { background: #f3f7fc; }
                #MainTabs, QTabWidget#MainTabs { background: #f3f7fc; }
                #Header {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fbfdff, stop:0.55 #eef5ff, stop:1 #e3edf9);
                    border-bottom: 1px solid #d8e5f4;
                }
                #HeaderTitle { color: #43658a; font-size: 30px; font-weight: 800; letter-spacing: 0.4px; }
                #HeaderSubtitle { color: #7f9ab9; font-size: 13px; }
                #HeaderTag {
                    color: #6783a5; background: rgba(255, 255, 255, 0.94); border: 1px solid #dbe7f5;
                    border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700;
                }
                #HeaderStatusBadge {
                    color: #6481a3; background: #ffffff; border: 1px solid #dbe7f5;
                    border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;
                }
                QTabWidget::pane { border: 0; background: #f5f9fe; top: -1px; }
                QWidget#qt_tabwidget_stackedwidget { background: #f5f9fe; }
                QTabBar { background: #f5f9fe; }
                QTabWidget::tab-bar { left: 12px; }
                QTabBar::tab {
                    background: #e8f0fa; color: #6c88aa; padding: 12px 20px; margin: 8px 6px 0 0;
                    border: 1px solid #d7e4f3; border-bottom: 0; border-top-left-radius: 12px; border-top-right-radius: 12px; font-weight: 700;
                }
                QTabBar::tab:selected { background: #ffffff; color: #4f719b; border-color: #c9dbef; }
                QTabBar::tab:hover:!selected { background: #edf4fc; color: #5f80a7; }
                QTabBar::scroller { background: transparent; width: 18px; }
                QTabBar QToolButton {
                    background: #eef5fd; color: #6f8dae; border: 1px solid #d7e4f3; border-radius: 8px; padding: 4px 8px;
                }
                QTabBar QToolButton:hover { background: #e4eefb; color: #587a9f; border-color: #c9dbef; }
                QScrollArea { border: 0; background: #f5f9fe; }
                #CapturePage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f5f9ff); }
                #RecordPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #eef5ff); }
                #LongshotPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f0f8ff); }
                #AppPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f3f8ff); }
                #LogPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f7fbff); }
                QGroupBox {
                    background: #ffffff; border: 1px solid #dce7f3; border-radius: 16px;
                    margin-top: 18px; padding-top: 8px; font-weight: 800; color: #6483a8;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 16px; padding: 2px 10px;
                    background: #f7fbff; color: #6788ae; border: 1px solid #dce7f3; border-radius: 8px;
                }
                QLabel { color: #6f8dae; }
               QRadioButton, QCheckBox { color: #6f8dae; background: transparent; spacing: 8px; }
               QRadioButton::indicator, QCheckBox::indicator {
                   width: 18px; height: 18px; border-radius: 9px;
                   border: 1px solid transparent; background: rgba(255, 255, 255, 0.55);
               }
               QCheckBox::indicator { border-radius: 6px; }
               QRadioButton::indicator:hover, QCheckBox::indicator:hover {
                   border: 1px solid rgba(125, 161, 199, 0.06); background: rgba(255, 255, 255, 0.88);
               }
               QRadioButton::indicator:checked, QCheckBox::indicator:checked {
                   border: 1px solid rgba(0, 0, 0, 0.3); background: rgba(0, 0, 0, 0.8);
               }
                QLineEdit, QComboBox, QTextEdit, QTableWidget {
                    background: #fbfdff; border: 1px solid #d9e6f3; border-radius: 12px; padding: 8px; color: #4f6f94;
                }
                QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTableWidget:focus {
                    border: 2px solid #bfd6ee; background: #ffffff;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
                    border-left: 1px solid #d9e6f3; background: #f3f8fe; border-top-right-radius: 10px; border-bottom-right-radius: 10px;
                }
                QComboBox::down-arrow { image: none; width: 0; height: 0; }
                QComboBox QAbstractItemView {
                    background: #ffffff; color: #56779e; border: 1px solid #d7e4f3;
                    selection-background-color: #e8f2fc; selection-color: #47698f; outline: 0;
                }
                QComboBox QAbstractItemView::item { padding: 6px 10px; }
                QTextEdit#LogConsole {
                    background: #f8fbff; color: #54759b; border: 1px solid #d9e6f3; border-radius: 12px;
                    selection-background-color: #dbeafe; selection-color: #45668f; font-family: 'JetBrains Mono'; font-size: 12px;
                }
                QPushButton {
                    border: 1px solid #d9e3ef; border-radius: 12px; padding: 10px 14px; background: #ffffff; color: #6783a5; font-weight: 700;
                }
                QPushButton:hover { background: #f3f8fe; border-color: #cbdced; color: #557396; }
                QPushButton[role='primary'] { background: #eaf2fd; color: #4b77a8; border: 1px solid #d5e3f5; }
                QPushButton[role='primary']:hover { background: #e2ecfb; }
                QPushButton[role='danger'] { background: #fff2f4; color: #b97a8e; border: 1px solid #f1d9e0; }
                QPushButton[role='danger']:hover { background: #fdecef; }
                QPushButton[role='accent'] { background: #eef7ff; color: #5d82ad; border: 1px solid #d8e8f7; }
                QPushButton[role='accent']:hover { background: #e6f1fc; }
                QPushButton[role='ghost'] { background: #ffffff; color: #6f8dae; border: 1px solid #d9e6f3; }
                QPushButton[role='ghost']:hover { background: #f7fbff; }
                QPushButton[role='start-capture'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dcecff, stop:1 #cfe2fb);
                    color: #416a97; border: 1px solid #bdd4ee; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='start-capture']:hover { background: #cfe2fb; border-color: #aec8e7; color: #365f8b; }
                QPushButton[role='start-capture']:disabled { background: #eff5fc; color: #aabdcf; border-color: #dce8f4; }
                QPushButton[role='start-record'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d8f0f8, stop:1 #cae6f4);
                    color: #4d7893; border: 1px solid #bcdbea; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='start-record']:hover { background: #cae6f4; border-color: #acd1e4; color: #436c86; }
                QPushButton[role='start-record']:disabled { background: #eef6fa; color: #a9bfcc; border-color: #dce9f0; }
                QPushButton[role='stop-capture'], QPushButton[role='stop-record'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe8ee, stop:1 #f9d9e2);
                    color: #ad6f84; border: 1px solid #edc4d0; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='stop-capture']:hover, QPushButton[role='stop-record']:hover { background: #f9d9e2; border-color: #e8b6c6; color: #a16178; }
                QPushButton[role='stop-capture']:disabled, QPushButton[role='stop-record']:disabled { background: #fdf6f8; color: #cbb8c1; border-color: #f1e1e7; }
                QHeaderView::section {
                    background: #f3f8fe; color: #6382a6; padding: 9px; border: 0; font-weight: 800;
                }
                QTableWidget {
                    gridline-color: #e6eef7; alternate-background-color: #f8fbff; selection-background-color: #e9f2fc; selection-color: #4e7097;
                }
                QTableCornerButton::section {
                    background: #f3f8fe; border: 1px solid #d9e6f3;
                }
                QScrollBar:vertical {
                    background: #eef4fb; width: 12px; margin: 4px 2px 4px 2px; border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #c8d9ec; min-height: 28px; border-radius: 6px;
                }
                QScrollBar::handle:vertical:hover { background: #b6cce5; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: transparent; height: 0px;
                }
                QScrollBar:horizontal {
                    background: #eef4fb; height: 12px; margin: 2px 4px 2px 4px; border-radius: 6px;
                }
                QScrollBar::handle:horizontal {
                    background: #c8d9ec; min-width: 28px; border-radius: 6px;
                }
                QScrollBar::handle:horizontal:hover { background: #b6cce5; }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                    background: transparent; width: 0px;
                }
                QStatusBar { background: #f4f8fd; color: #7391b0; font-weight: 700; border-top: 1px solid #dce7f3; }
                """
            return """
                QMainWindow { background: #f7f3f2; }
                #MainTabs, QTabWidget#MainTabs { background: #f7f3f2; }
                #Header { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fffdfc, stop:0.55 #f8f2f5, stop:1 #eef3fb); border-bottom: 1px solid #eadfe5; }
                #HeaderTitle { color: #9e8997; font-size: 28px; font-weight: 800; }
                #HeaderSubtitle { color: #b29fad; font-size: 13px; }
                #HeaderStatusBadge {
                    color: #ab97a6; background: #fffafc; border: 1px solid #eadfe6;
                    border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;
                }
                QTabWidget::pane { border: 0; background: #faf7f7; top: -1px; }
                QWidget#qt_tabwidget_stackedwidget { background: #faf7f7; }
                QTabBar { background: #faf7f7; }
                QTabWidget::tab-bar { left: 12px; }
                QTabBar::tab {
                    background: #f4ebef; color: #b09ca9; padding: 12px 20px; margin: 8px 6px 0 0;
                    border: 1px solid #e7d9e1; border-bottom: 0; border-top-left-radius: 12px; border-top-right-radius: 12px; font-weight: 700;
                }
                QTabBar::tab:selected { background: #fffdfd; color: #9c7f92; border-color: #dfced8; }
                QTabBar::tab:hover:!selected { background: #f9f2f5; color: #a58a9a; }
                QTabBar::scroller { background: transparent; width: 18px; }
                QTabBar QToolButton {
                    background: #f7eff3; color: #b09ca9; border: 1px solid #e7d9e1; border-radius: 8px; padding: 4px 8px;
                }
                QTabBar QToolButton:hover { background: #f3e8ed; color: #9f8797; border-color: #dfced8; }
                QScrollArea { border: 0; background: #faf7f7; }
                #CapturePage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffdfc, stop:1 #f9f1f3); }
                #RecordPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffdfc, stop:1 #f2f4fb); }
                #LongshotPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffdfd, stop:1 #eef6fb); }
                #AppPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffefd, stop:1 #f6f1f8); }
                #LogPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffdfd, stop:1 #f7f2f5); }
                QGroupBox {
                    background: #fffdfd; border: 1px solid #eee4ea; border-radius: 16px;
                    margin-top: 18px; padding-top: 8px; font-weight: 800; color: #aa97a6;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 16px; padding: 2px 10px;
                    background: #fff9fb; color: #aa97a6; border: 1px solid #eee4ea; border-radius: 8px;
                }
                QLabel { color: #ad99a8; }
               QRadioButton, QCheckBox { color: #ad99a8; background: transparent; spacing: 8px; }
               QRadioButton::indicator, QCheckBox::indicator {
                   width: 18px; height: 18px; border-radius: 9px;
                   border: 1px solid transparent; background: rgba(255, 253, 253, 0.58);
               }
               QCheckBox::indicator { border-radius: 6px; }
               QRadioButton::indicator:hover, QCheckBox::indicator:hover {
                   border: 1px solid rgba(222, 198, 209, 0.06); background: rgba(255, 250, 252, 0.90);
               }
               QRadioButton::indicator:checked, QCheckBox::indicator:checked {
                   border: 1px solid rgba(0, 0, 0, 0.3); background: rgba(0, 0, 0, 0.8);
               }
                QLineEdit, QComboBox, QTextEdit, QTableWidget {
                    background: #fffefe; border: 1px solid #eee5ea; border-radius: 10px; padding: 8px; color: #b09eab;
                }
                QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTableWidget:focus {
                    border: 2px solid #e8dbe4; background: #ffffff;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
                    border-left: 1px solid #eee5ea; background: #faf4f6; border-top-right-radius: 10px; border-bottom-right-radius: 10px;
                }
                QComboBox::down-arrow { image: none; width: 0; height: 0; }
                QComboBox QAbstractItemView {
                    background: #fffdfd; color: #aa97a6; border: 1px solid #e7dce3;
                    selection-background-color: #f7edf2; selection-color: #9d8698; outline: 0;
                }
                QComboBox QAbstractItemView::item { padding: 6px 10px; }
                QTextEdit#LogConsole {
                    background: #fffafb; color: #b39fac; border: 1px solid #eee5ea; border-radius: 12px;
                    selection-background-color: #f4e9ef; selection-color: #a48f9f; font-family: 'JetBrains Mono'; font-size: 12px;
                }
                QPushButton {
                    border: 1px solid #e9e1e6; border-radius: 10px; padding: 10px 14px; background: #fffdfd; color: #ab98a7; font-weight: 700;
                }
                QPushButton:hover { background: #faf5f7; border-color: #e4d9e0; color: #9f8a9b; }
                QPushButton[role='primary'] { background: #f3eef8; color: #9c8fb0; border: 1px solid #e5ddf1; }
                QPushButton[role='primary']:hover { background: #eee8f6; }
                QPushButton[role='danger'] { background: #fdf4f6; color: #c4a1ab; border: 1px solid #f1e1e6; }
                QPushButton[role='danger']:hover { background: #faedf1; }
                QPushButton[role='accent'] { background: #eef5fc; color: #93a7c2; border: 1px solid #e0e9f6; }
                QPushButton[role='accent']:hover { background: #e8f0fa; }
                QPushButton[role='ghost'] { background: #fffefe; color: #b09eab; border: 1px solid #eee5ea; }
                QPushButton[role='ghost']:hover { background: #fff8fb; }
                QPushButton[role='start-capture'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f8eaf1, stop:1 #f3dde8);
                    color: #9d7389; border: 1px solid #e9cddd; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='start-capture']:hover { background: #f3dde8; border-color: #dfbfd2; color: #946a81; }
                QPushButton[role='start-capture']:disabled { background: #fbf4f7; color: #c8b7c0; border-color: #f0e4ea; }
                QPushButton[role='start-record'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #eaf1fb, stop:1 #dde8f7);
                    color: #788ead; border: 1px solid #cad9ee; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='start-record']:hover { background: #dde8f7; border-color: #bfd0e9; color: #6c84a5; }
                QPushButton[role='start-record']:disabled { background: #f4f7fc; color: #bac5d8; border-color: #e5ecf6; }
                QPushButton[role='stop-capture'], QPushButton[role='stop-record'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fdf1f4, stop:1 #f8dfe7);
                    color: #b27b8e; border: 1px solid #efccd8; min-width: 168px; min-height: 52px;
                    font-size: 16px; font-weight: 800;
                }
                QPushButton[role='stop-capture']:hover, QPushButton[role='stop-record']:hover { background: #f8dfe7; border-color: #e9bccd; color: #a66f84; }
                QPushButton[role='stop-capture']:disabled, QPushButton[role='stop-record']:disabled { background: #fdf7f9; color: #d0bcc4; border-color: #f3e4ea; }
                QHeaderView::section {
                    background: #fbf6f8; color: #ab98a7; padding: 8px; border: 0; font-weight: 800;
                }
                QTableWidget {
                    gridline-color: #f2eaee; alternate-background-color: #fffafb; selection-background-color: #f6edf2; selection-color: #a591a1;
                }
                QTableCornerButton::section {
                    background: #fbf6f8; border: 1px solid #eee5ea;
                }
                QScrollBar:vertical {
                    background: #f7f0f3; width: 12px; margin: 4px 2px 4px 2px; border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #e1d0d8; min-height: 28px; border-radius: 6px;
                }
                QScrollBar::handle:vertical:hover { background: #d7c1cb; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: transparent; height: 0px;
                }
                QScrollBar:horizontal {
                    background: #f7f0f3; height: 12px; margin: 2px 4px 2px 4px; border-radius: 6px;
                }
                QScrollBar::handle:horizontal {
                    background: #e1d0d8; min-width: 28px; border-radius: 6px;
                }
                QScrollBar::handle:horizontal:hover { background: #d7c1cb; }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                    background: transparent; width: 0px;
                }
                QStatusBar { background: #faf5f7; color: #b19dab; font-weight: 700; border-top: 1px solid #ece2e8; }
                """

        def _apply_styles(self):
            self._base_stylesheet = self._theme_stylesheet()
            self.setStyleSheet(self._base_stylesheet)
            self._apply_dynamic_font_scale()

        def _apply_dynamic_font_scale(self):
            width = max(self.width(), self.minimumWidth())
            scale = max(0.90, min(1.35, width / 1320.0))

            def px(value: int) -> int:
                return max(10, int(round(value * scale)))

            dynamic_stylesheet = f"""
                #HeaderTitle {{ font-size: {px(28)}px; }}
                #HeaderSubtitle {{ font-size: {px(13)}px; }}
                #HeaderStatusBadge {{ font-size: {px(13)}px; padding: {px(8)}px {px(14)}px; }}
                QTabBar::tab {{ font-size: {px(13)}px; padding: {px(12)}px {px(20)}px; }}
                QGroupBox {{ font-size: {px(13)}px; }}
                QLabel, QLineEdit, QComboBox, QCheckBox, QRadioButton, QTableWidget, QTableWidgetItem {{ font-size: {px(13)}px; }}
                QLineEdit, QComboBox {{ min-height: {px(22)}px; padding-top: {px(8)}px; padding-bottom: {px(8)}px; }}
                QRadioButton, QCheckBox {{ spacing: {px(8)}px; min-height: {px(22)}px; }}
                QPushButton {{ font-size: {px(14)}px; padding: {px(10)}px {px(14)}px; min-height: {px(22)}px; }}
                QTextEdit#LogConsole {{ font-size: {px(12)}px; }}
                QStatusBar {{ font-size: {px(13)}px; }}
                """
            self.setStyleSheet(self._base_stylesheet + dynamic_stylesheet)
            if hasattr(self, "app_table"):
                for row in range(self.app_table.rowCount()):
                    self.app_table.setRowHeight(row, px(42))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._apply_dynamic_font_scale()

        def _make_scroll_page(self) -> tuple[QWidget, QWidget]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(self._qt_scrollbar_always_off())
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(14)
            layout.addStretch(1)
            scroll.setWidget(container)
            return scroll, container

        def _make_button(self, text: str, handler, role: str = "") -> QPushButton:
            btn = QPushButton(text)
            if role:
                btn.setProperty("role", role)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            btn.clicked.connect(handler)
            return btn

        def _qt_checked_value(self):
            value = getattr(Qt, "Checked", None)
            if value is None and hasattr(Qt, "CheckState"):
                value = Qt.CheckState.Checked
            return int(value)

        def _qt_align_center(self):
            value = getattr(Qt, "AlignCenter", None)
            if value is None and hasattr(Qt, "AlignmentFlag"):
                value = Qt.AlignmentFlag.AlignCenter
            return value

        def _qt_align_left(self):
            value = getattr(Qt, "AlignLeft", None)
            if value is None and hasattr(Qt, "AlignmentFlag"):
                value = Qt.AlignmentFlag.AlignLeft
            return value

        def _qt_scrollbar_always_off(self):
            value = getattr(Qt, "ScrollBarAlwaysOff", None)
            if value is None and hasattr(Qt, "ScrollBarPolicy"):
                value = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            return value

        def _qt_item_is_editable_flag(self):
            value = getattr(Qt, "ItemIsEditable", None)
            if value is None and hasattr(Qt, "ItemFlag"):
                value = Qt.ItemFlag.ItemIsEditable
            return value

        def _qt_no_selection_mode(self):
            value = getattr(QAbstractItemView, "NoSelection", None)
            if value is None and hasattr(QAbstractItemView, "SelectionMode"):
                value = QAbstractItemView.SelectionMode.NoSelection
            return value

        def _qt_no_edit_triggers(self):
            value = getattr(QAbstractItemView, "NoEditTriggers", None)
            if value is None and hasattr(QAbstractItemView, "EditTrigger"):
                value = QAbstractItemView.EditTrigger.NoEditTriggers
            return value

        def _header_resize_mode(self, name: str):
            value = getattr(QHeaderView, name, None)
            if value is None and hasattr(QHeaderView, "ResizeMode"):
                value = getattr(QHeaderView.ResizeMode, name)
            return value

        def _messagebox_yes_value(self):
            value = getattr(QMessageBox, "Yes", None)
            if value is None and hasattr(QMessageBox, "StandardButton"):
                value = QMessageBox.StandardButton.Yes
            return value

        def _build_shared_panel(self, parent: QWidget, mode_kind: str) -> FieldBundle:
            layout = parent.layout()
            assert layout is not None

            hero = QGroupBox("功能总览")
            hero_layout = QVBoxLayout(hero)
            hero_layout.setContentsMargins(16, 18, 16, 16)
            hero_layout.setSpacing(6)
            hero_title_map = {
                "capture": "截图模式 · 自动采集 / 手动截图 / 重点内容识别",
                "record": "录屏模式 · MP4 录制 / 自动滑动 / 手动控制",
                "longshot": "长截图模式 · 系统增强 / 滚动拼接 / 自动回退",
            }
            hero_desc_map = {
                "capture": "适合快速采集聊天记录、重点内容或单张截图，支持按会话自动归档。",
                "record": "适合录制聊天过程或完整页面，支持从顶部或当前位置开始。",
                "longshot": "适合输出完整长图，优先使用系统能力，失败时自动切换为滚动拼接。",
            }
            hero_title = QLabel(hero_title_map.get(mode_kind, "当前模式概览"))
            hero_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #4f719b;")
            hero_desc = QLabel(hero_desc_map.get(mode_kind, "点击下方区域开始配置当前模式。"))
            hero_desc.setStyleSheet("color: #7f9ab9;")
            hero_layout.addWidget(hero_title)
            hero_layout.addWidget(hero_desc)
            layout.insertWidget(layout.count() - 1, hero)

            form_box = QGroupBox("基础信息")
            form_grid = QGridLayout(form_box)
            form_grid.setContentsMargins(16, 18, 16, 16)
            form_grid.setHorizontalSpacing(16)
            form_grid.setVerticalSpacing(14)
            form_grid.setColumnStretch(0, 0)
            form_grid.setColumnStretch(1, 1)
            form_grid.setColumnStretch(2, 0)

            labels = ["设备", "App 名称", "包名", "聊天标题", "输出根目录", "会话名称"]
            edits = [QLineEdit() for _ in labels]
            defaults = [
                "未检测",
                "未识别",
                "未识别",
                "未识别",
                CONFIG["output_root"],
                f"session_{datetime.now():%Y%m%d_%H%M%S}",
            ]

            btn_detect_device = self._make_button("检测设备", self.detect_device)
            btn_detect_app = self._make_button("检测 App", self.detect_app)
            btn_detect_title = self._make_button("识别标题", self.detect_title)
            btn_choose_dir = self._make_button("选择目录", self.choose_output_root)

            button_map = {
                "设备": btn_detect_device,
                "App 名称": btn_detect_app,
                "聊天标题": btn_detect_title,
                "输出根目录": btn_choose_dir,
            }

            for i, (label_text, edit, default) in enumerate(zip(labels, edits, defaults)):
                edit.setText(default)
                edit.setMinimumHeight(40)
                label = QLabel(label_text)
                label.setMinimumWidth(88)
                label.setWordWrap(False)
                form_grid.addWidget(label, i, 0)
                form_grid.addWidget(edit, i, 1)

                if label_text in button_map:
                    btn = button_map[label_text]
                    btn.setMinimumHeight(40)
                    form_grid.addWidget(btn, i, 2)

            layout.insertWidget(layout.count() - 1, form_box)

            mode_title_map = {"capture": "截图模式", "record": "录屏模式", "longshot": "长截图模式"}
            mode_box = QGroupBox(mode_title_map.get(mode_kind, "模式"))
            mode_layout = QVBoxLayout(mode_box)
            mode_layout.setContentsMargins(16, 18, 16, 16)
            mode_layout.setSpacing(8)

            def add_mode_row(value: int, text: str, button_store: list, custom_checkbox: QCheckBox | None = None, checked: bool = False):
                row = QHBoxLayout()
                row.setSpacing(10)
                radio = QRadioButton(text)
                radio.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                if checked:
                    radio.setChecked(True)
                button_store.append((value, radio))
                row.addWidget(radio, 0, self._qt_align_left())
                if custom_checkbox is not None:
                    custom_checkbox.setText("自定义命名")
                    custom_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                    row.addSpacing(4)
                    row.addWidget(custom_checkbox, 0, self._qt_align_left())
                row.addStretch(1)
                mode_layout.addLayout(row)

            if mode_kind == "capture":
                self.capture_mode_buttons = []
                self.capture_custom_name_checkbox = QCheckBox("使用自定义命名")
                for value, text in [
                    (1, "模式1：自动判断到顶后开始向下截图"),
                    (2, "模式2：单张手动截图"),
                    (3, "模式3：从当前位置开始自动向下截图，不判断顶端"),
                    (4, "模式4：自动识别 APK / 链接 / 账号并截取上下文"),
                ]:
                    add_mode_row(value, text, self.capture_mode_buttons, self.capture_custom_name_checkbox if value == 2 else None, value == 1)
            elif mode_kind == "record":
                self.record_mode_buttons = []
                self.record_custom_name_checkbox = QCheckBox("使用自定义命名")
                for value, text in [
                    (1, "模式1：先快速到顶部，再向下录制 MP4 视频"),
                    (2, "模式2：手动滑动，开始/停止录屏"),
                    (3, "模式3：从当前位置开始自动向下滑动录屏，不判断顶端"),
                ]:
                    add_mode_row(value, text, self.record_mode_buttons, self.record_custom_name_checkbox if value == 2 else None, value == 1)
            else:
                self.longshot_mode_buttons = []
                self.longshot_custom_name_checkbox = QCheckBox("使用自定义命名")
                for value, text in [
                    (1, "模式1：系统长截图增强优先，失败自动回退拼接"),
                    (2, "模式2：从当前位置开始抓取并拼接，可自定义命名"),
                    (3, "模式3：从当前位置开始自动向下抓取并拼接，不判断顶端"),
                ]:
                    add_mode_row(value, text, self.longshot_mode_buttons, self.longshot_custom_name_checkbox if value == 2 else None, value == 1)
            layout.insertWidget(layout.count() - 1, mode_box)

            control_title_map = {"capture": "截图控制区", "record": "录屏控制区", "longshot": "长截图控制区"}
            control_box = QGroupBox(control_title_map.get(mode_kind, "控制区"))
            control_layout = QVBoxLayout(control_box)
            control_layout.setContentsMargins(16, 18, 16, 16)
            control_layout.setSpacing(10)
            title_map = {"capture": "截图任务控制台", "record": "视频录屏控制台", "longshot": "长截图拼接控制台"}
            desc_map = {
                "capture": "点击开始按钮执行任务，模式4 会自动识别 APK / 链接 / 账号并裁取上下文。",
                "record": "点击开始按钮执行任务，停止按钮会立即尝试中断任务。",
                "longshot": "优先尝试系统长截图增强；若设备不支持或识别失败，会自动回退为滚动抓图拼接 PNG。",
            }
            title = QLabel(title_map.get(mode_kind, "任务控制台"))
            title.setStyleSheet("font-size: 17px; font-weight: 800; color: #4f719b;")
            desc = QLabel(desc_map.get(mode_kind, "点击开始按钮执行任务。"))
            desc.setStyleSheet("color: #7f9ab9;")
            control_layout.addWidget(title)
            control_layout.addWidget(desc)
            button_bar = QHBoxLayout()
            button_bar.setSpacing(10)
            if mode_kind == "capture":
                self.capture_start_btn = self._make_button("开始截图", self.start_screenshot, role="start-capture")
                self.capture_stop_btn = self._make_button("停止截图", self.stop_screenshot, role="stop-capture")
                self.capture_stop_btn.setEnabled(False)
                button_bar.addWidget(self.capture_start_btn)
                button_bar.addWidget(self.capture_stop_btn)
            elif mode_kind == "record":
                self.record_start_btn = self._make_button("开始录屏", self.start_recording, role="start-record")
                self.record_stop_btn = self._make_button("停止录屏", self.stop_recording, role="stop-record")
                self.record_stop_btn.setEnabled(False)
                button_bar.addWidget(self.record_start_btn)
                button_bar.addWidget(self.record_stop_btn)
            else:
                self.longshot_start_btn = self._make_button("始长截图", self.start_longshot, role="start-capture")
                self.longshot_stop_btn = self._make_button("停止长截图", self.stop_longshot, role="stop-capture")
                self.longshot_stop_btn.setEnabled(False)
                button_bar.addWidget(self.longshot_start_btn)
                button_bar.addWidget(self.longshot_stop_btn)
            button_bar.addWidget(self._make_button("创建/刷新项目", self.refresh_project, role="accent"))
            button_bar.addWidget(self._make_button("打开输出目录", self.open_project_dir))
            control_layout.addLayout(button_bar)
            layout.insertWidget(layout.count() - 1, control_box)

            brand_box = QGroupBox("品牌 / 状态")
            brand_layout = QVBoxLayout(brand_box)
            brand_layout.setContentsMargins(16, 18, 16, 16)
            brand_layout.setSpacing(8)
            brand_desc_map = {
                "capture": "截图模块 · 纯本地处理",
                "record": "录屏模块 · 原生 MP4 导出",
                "longshot": "长截图模块 · 自动滚动拼接 PNG",
            }
            brand_desc = QLabel(brand_desc_map.get(mode_kind, "模块 · 纯本地处理"))
            brand_desc.setStyleSheet("color: #7f9ab9; font-weight: 700;")
            brand_hint = QLabel("各页面任务相互隔离，仅管理当前模式下的项目、日志与按钮状态")
            brand_hint.setStyleSheet("color: #8ba0bb;")
            status_label = QLabel("状态：就绪")
            status_label.setObjectName(f"statusLabel_{mode_kind}")
            brand_layout.addWidget(brand_desc)
            brand_layout.addWidget(brand_hint)
            brand_layout.addWidget(status_label)
            layout.insertWidget(layout.count() - 1, brand_box)

            custom_name_checkbox = None
            if mode_kind == "capture":
                self.capture_status_label = status_label
                custom_name_checkbox = self.capture_custom_name_checkbox
            elif mode_kind == "record":
                self.record_status_label = status_label
                custom_name_checkbox = self.record_custom_name_checkbox
            else:
                self.longshot_status_label = status_label
                custom_name_checkbox = self.longshot_custom_name_checkbox

            bundle = FieldBundle(*edits, custom_name_checkbox=custom_name_checkbox)
            if bundle.custom_name_checkbox is not None:
                fallback_prefix = {
                    "capture": "capture",
                    "record": "record",
                    "longshot": "longshot",
                }.get(mode_kind, "session")
                bundle.custom_name_checkbox.toggled.connect(
                    lambda checked, b=bundle, prefix=fallback_prefix: self._sync_session_name_with_custom_toggle(b, checked, prefix)
                )
                if not bundle.custom_name_checkbox.isChecked():
                    bundle.session_name.setText(self._default_session_name(bundle, fallback_prefix))
            return bundle

        def _build_app_panel(self, parent: QWidget):
            layout = parent.layout()
            assert layout is not None


            head = QGroupBox("已安装 App 列表")
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(16, 18, 16, 16)
            self.app_search_input = QLineEdit()
            self.app_search_input.setPlaceholderText("搜索名称 / 包名 / 安装来源")
            self.app_search_input.textChanged.connect(self._on_app_filter_changed)
            head_layout.addWidget(QLabel("搜索"))
            head_layout.addWidget(self.app_search_input, 1)
            head_layout.addStretch(1)
            layout.insertWidget(layout.count() - 1, head)

            actions = QGroupBox("App 操作区")
            actions_layout = QVBoxLayout(actions)
            actions_layout.setContentsMargins(16, 18, 16, 16)
            actions_layout.setSpacing(12)

            system_row = QHBoxLayout()
            system_row.setSpacing(10)
            self.include_system_checkbox = QCheckBox("包含系统应用")
            self.include_system_checkbox.setChecked(False)
            self.include_system_checkbox.stateChanged.connect(lambda _v: self.refresh_app_list())
            self.include_system_checkbox.setStyleSheet("""
                QCheckBox {
                    padding: 6px 12px;
                    border-radius: 10px;
                    border: 1px solid #d7e4f3;
                    background: #fff7f7;
                    color: #9a6b6b;
                    font-weight: 800;
                }
                QCheckBox:hover {
                    border-color: #c9d7e6;
                }
                QCheckBox:checked {
                    background: #eaf2fd;
                    border-color: #bcd2ea;
                    color: #4b77a8;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 5px;
                    border: 1px solid #cbd8e6;
                    background: #ffffff;
                }
                QCheckBox::indicator:unchecked {
                    background: #fffefe;
                }
                QCheckBox::indicator:checked {
                    background: #2563eb;
                    border-color: #1d4ed8;
                }
            """)
            system_row.addWidget(self.include_system_checkbox)
            system_row.addWidget(self._make_button("刷新列表", self.refresh_app_list, role="accent"))
            self.export_selected_apk_btn = self._make_button("导出勾选 APK", self.export_selected_apps, role="primary")
            system_row.addWidget(self.export_selected_apk_btn)
            system_row.addWidget(self._make_button("打开导出目录", self.open_app_export_dir, role="ghost"))
            system_row.addStretch(1)
            actions_layout.addLayout(system_row)

            layout.insertWidget(layout.count() - 1, actions)

            self.app_table = QTableWidget(0, 5)
            self.app_table.setHorizontalHeaderLabels(["选中", "名称", "包名", "安装来源", "操作"])
            self.app_table.setAlternatingRowColors(True)
            self.app_table.verticalHeader().setVisible(False)
            self.app_table.setSelectionMode(self._qt_no_selection_mode())
            self.app_table.setEditTriggers(self._qt_no_edit_triggers())
            self.app_table.horizontalHeader().setSectionResizeMode(0, self._header_resize_mode("ResizeToContents"))
            self.app_table.horizontalHeader().setSectionResizeMode(1, self._header_resize_mode("Stretch"))
            self.app_table.horizontalHeader().setSectionResizeMode(2, self._header_resize_mode("Stretch"))
            self.app_table.horizontalHeader().setSectionResizeMode(3, self._header_resize_mode("Stretch"))
            self.app_table.horizontalHeader().setSectionResizeMode(4, self._header_resize_mode("ResizeToContents"))
            self.app_table.setMinimumHeight(520)
            layout.insertWidget(layout.count() - 1, self.app_table)

            footer = QGroupBox("分页信息")
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(16, 16, 16, 16)
            footer_layout.setSpacing(12)

            self.app_page_label = QLabel("点击刷新列表加载 App 数据")
            self.app_page_label.setStyleSheet("color: #7f9ab9; font-weight: 700;")
            footer_layout.addWidget(self.app_page_label)

            self.page_size_combo = QComboBox()
            self.page_size_combo.addItems(["10", "20", "30"])
            self.page_size_combo.setCurrentText("10")
            self.page_size_combo.currentTextChanged.connect(self.change_app_page_size)
            footer_layout.addSpacing(12)
            footer_layout.addWidget(QLabel("每页显示"))
            footer_layout.addWidget(self.page_size_combo)

            footer_layout.addStretch(1)
            self.app_prev_page_btn = self._make_button("上一页", self.app_prev_page)
            self.app_next_page_btn = self._make_button("下一页", self.app_next_page)
            footer_layout.addWidget(self.app_prev_page_btn)
            footer_layout.addWidget(self.app_next_page_btn)

            layout.insertWidget(layout.count() - 1, footer)

            self.app_filter_summary_label = QLabel("筛选结果：0 项")
            self.app_filter_summary_label.setStyleSheet("color: #8ba0bb; font-weight: 700;")
            layout.insertWidget(layout.count() - 1, self.app_filter_summary_label)

        def _build_log_panel(self, parent: QWidget):
            layout = parent.layout()
            assert layout is not None

            hero = QGroupBox("运行日志中心")
            hero_layout = QVBoxLayout(hero)
            hero_layout.setContentsMargins(16, 18, 16, 16)
            hero_layout.setSpacing(6)
            hero_title = QLabel("Runtime Console")
            hero_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #4f719b;")
            hero_desc = QLabel("实时查看任务状态、ADB 执行过程、导出记录与异常信息，排查问题更直接。")
            hero_desc.setStyleSheet("color: #7f9ab9;")
            hero_layout.addWidget(hero_title)
            hero_layout.addWidget(hero_desc)
            layout.insertWidget(layout.count() - 1, hero)

            tools = QGroupBox("日志操作")
            tools_layout = QHBoxLayout(tools)
            tools_layout.setContentsMargins(16, 18, 16, 16)
            self.log_line_count_label = QLabel("日志 0 条")
            self.log_line_count_label.setStyleSheet("color: #7f9ab9; font-weight: 800;")
            self.log_autoscroll_checkbox = QCheckBox("自动滚动到底部")
            self.log_autoscroll_checkbox.setChecked(True)
            tools_layout.addWidget(self.log_line_count_label)
            tools_layout.addSpacing(12)
            tools_layout.addWidget(self.log_autoscroll_checkbox)
            tools_layout.addWidget(self._make_button("刷新视图", self._refresh_runtime_log_view))
            tools_layout.addWidget(self._make_button("从磁盘重载", self.reload_runtime_log_from_disk))
            tools_layout.addWidget(self._make_button("打开日志目录", self.open_log_dir, role="ghost"))
            tools_layout.addWidget(self._make_button("导出日志副本", self.export_runtime_log_copy, role="accent"))
            tools_layout.addWidget(self._make_button("清空界面日志", self.clear_runtime_log_view, role="danger"))
            tools_layout.addStretch(1)
            layout.insertWidget(layout.count() - 1, tools)

            self.log_text = QTextEdit()
            self.log_text.setObjectName("LogConsole")
            self.log_text.setReadOnly(True)
            self.log_text.setMinimumHeight(560)
            layout.insertWidget(layout.count() - 1, self.log_text)

            self.log_hint_label = QLabel("提示：日志支持磁盘重载和导出副本，适合在任务执行中快速排查问题。")
            self.log_hint_label.setStyleSheet("color: #8ba0bb; font-weight: 700;")
            layout.insertWidget(layout.count() - 1, self.log_hint_label)

        def _sync_shared_fields(self, source: FieldBundle | None = None):
            bundles = [self.capture_fields, self.record_fields, self.longshot_fields]
            if source is None:
                source = self.capture_fields
            values = {
                "device": source.device.text(),
                "app_name": source.app_name.text(),
                "package": source.package.text(),
                "project_root": source.project_root.text(),
            }
            for bundle in bundles:
                for key, value in values.items():
                    getattr(bundle, key).setText(value)

        def _selected_mode(self, mode_kind: str) -> int:
            if mode_kind == "record":
                buttons = self.record_mode_buttons
            elif mode_kind == "longshot":
                buttons = self.longshot_mode_buttons
            else:
                buttons = self.capture_mode_buttons
            for value, button in buttons:
                if button.isChecked():
                    return value
            return 1

        def _append_log(self, message: str):
            self.bridge.log_signal.emit(message)

        def _context_kind_from_tab_index(self, index: int) -> str:
            if index == 1:
                return "record"
            if index == 2:
                return "longshot"
            if index == 3:
                return "app"
            if index == 4:
                return self.current_context_kind if self.current_context_kind in {"capture", "record", "longshot", "app"} else "capture"
            return "capture"

        def _switch_context(self, mode_kind: str, load_log: bool = True) -> Path | None:
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                self.current_context_kind = mode_kind
                return None
            project_dir = self._project_dir_for_mode(mode_kind)
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=mode_kind)
            self.current_context_kind = mode_kind
            self.project_dir = project_dir
            if mode_kind in {"capture", "record", "longshot"}:
                self.capturer = self._capturer_for_mode(mode_kind)
            if load_log:
                self._load_runtime_log_for_current_project()
            return project_dir

        def _on_tab_changed(self, index: int):
            mode_kind = self._context_kind_from_tab_index(index)
            if not hasattr(self, "tabs"):
                self.current_context_kind = mode_kind
                return
            self._switch_context(mode_kind, load_log=True)
            self._schedule_auto_detect_context(mode_kind)

        def _schedule_auto_detect_context(self, mode_kind: str | None = None):
            if self.current_task_state == "running":
                return
            if not hasattr(self, "auto_detect_timer"):
                return
            target_mode = mode_kind or self.current_context_kind or "capture"
            if target_mode not in {"capture", "record", "longshot", "app"}:
                return
            if self._auto_detect_pending and self._last_scheduled_auto_detect_context == target_mode:
                return
            self._last_auto_detect_context = target_mode
            self._last_scheduled_auto_detect_context = target_mode
            self._auto_detect_pending = True
            self.auto_detect_timer.start()

        def _run_auto_detect_context(self):
            if not self._auto_detect_pending:
                return
            if self.current_task_state == "running":
                self._schedule_auto_detect_context(self._last_auto_detect_context)
                return
            self._auto_detect_pending = False
            self._last_scheduled_auto_detect_context = ""
            self.detect_device(auto=True, silent=True)
            self.detect_app(auto=True, silent=True)

        def _append_log_ui(self, message: str):
            if message == self._last_log_message:
                return
            self._last_log_message = message
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {message}"
            self.runtime_log_buffer.append(line)
            self.log_line_count_label.setText(f"日志 {len(self.runtime_log_buffer)} 条")
            self.log_text.append(line)
            if self.log_autoscroll_checkbox.isChecked():
                cursor = self.log_text.textCursor()
                end_op = getattr(QTextCursor, "End", None)
                if end_op is None:
                    end_op = QTextCursor.MoveOperation.End
                cursor.movePosition(end_op)
                self.log_text.setTextCursor(cursor)
            self._write_runtime_log_to_disk(line)

        def _write_runtime_log_to_disk(self, line: str):
            log_project_dir = self._project_dir_for_mode(self.current_task_kind if self.current_task_kind in {"capture", "record", "longshot", "app"} else self.current_context_kind)
            if log_project_dir is None:
                log_project_dir = self.project_dir
            if log_project_dir is None:
                return
            try:
                log_dir = log_project_dir / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                runtime_log = log_dir / "runtime.log"
                with open(runtime_log, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        def _set_status(self, message: str):
            self.bridge.status_signal.emit(message)

        def _set_task_state(self, kind: str, state: str):
            self.bridge.task_state_signal.emit(kind, state)

        def _apply_task_state_ui(self, kind: str, state: str):
            self.current_task_kind = kind
            self.current_task_state = state
            if kind in {"capture", "record", "app"}:
                self.current_context_kind = kind
            self._refresh_header_badge()
            self._update_action_buttons()

        def _refresh_header_badge(self):
            status_text = self.status_bar.currentMessage() or "就绪"
            prefix_map = {
                "capture": "截图",
                "record": "录屏",
                "longshot": "长截图",
                "app": "App",
                "idle": "空闲",
            }
            prefix = prefix_map.get(self.current_task_kind, "状态")
            self.header_status_badge.setText(f"● {prefix} · {status_text}")

            badge_styles = {
                "failed": "color: #b97a8e; background: #fff3f6; border: 1px solid #f1dbe2; border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;",
                "stopping": "color: #b28b74; background: #fff7f0; border: 1px solid #f2e2d5; border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;",
                "running": "color: #ffffff; background: #3b82f6; border: 2px solid #60a5fa; border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;",
                "idle": "color: #7391b0; background: #f7fbff; border: 1px solid #dce7f3; border-radius: 14px; padding: 8px 14px; font-size: 13px; font-weight: 800;",
            }
            state_key = self.current_task_state if self.current_task_state in badge_styles else "idle"
            self.header_status_badge.setStyleSheet(badge_styles[state_key])

        def _set_status_ui(self, message: str):
            self.status_bar.showMessage(message)
            target_kind = self.current_task_kind if self.current_task_kind in {"capture", "record", "longshot"} else self.current_context_kind
            if target_kind == "capture":
                self.capture_status_label.setText(f"状态：{message}")
            elif target_kind == "record":
                self.record_status_label.setText(f"状态：{message}")
            elif target_kind == "longshot":
                self.longshot_status_label.setText(f"状态：{message}")
            self._refresh_header_badge()
            self._update_action_buttons()

        def _update_action_buttons(self):
            capture_busy = self.current_task_kind == "capture" and self.current_task_state in {"running", "stopping"}
            record_busy = self.current_task_kind == "record" and self.current_task_state in {"running", "stopping"}
            longshot_busy = self.current_task_kind == "longshot" and self.current_task_state in {"running", "stopping"}
            app_busy = self.current_task_kind == "app" and self.current_task_state in {"running", "stopping"}
            any_busy = capture_busy or record_busy or longshot_busy

            if hasattr(self, "capture_start_btn"):
                self.capture_start_btn.setEnabled(not any_busy and not app_busy)
            if hasattr(self, "record_start_btn"):
                self.record_start_btn.setEnabled(not any_busy and not app_busy)
            if hasattr(self, "longshot_start_btn"):
                self.longshot_start_btn.setEnabled(not any_busy and not app_busy)
            if hasattr(self, "capture_stop_btn"):
                self.capture_stop_btn.setEnabled(capture_busy)
            if hasattr(self, "record_stop_btn"):
                self.record_stop_btn.setEnabled(record_busy)
            if hasattr(self, "longshot_stop_btn"):
                self.longshot_stop_btn.setEnabled(longshot_busy)
            if hasattr(self, "export_selected_apk_btn"):
                self.export_selected_apk_btn.setEnabled(not any_busy and not app_busy)
        def _current_runtime_log_path(self) -> Path | None:
            project_dir = self._project_dir_for_mode(self.current_context_kind)
            if project_dir is None:
                project_dir = self.project_dir
            if project_dir is None:
                return None
            return project_dir / "logs" / "runtime.log"

        def _refresh_runtime_log_view(self):
            self.log_text.setPlainText("\n".join(self.runtime_log_buffer))
            self.log_line_count_label.setText(f"日志 {len(self.runtime_log_buffer)} 条")
            cursor = self.log_text.textCursor()
            end_op = getattr(QTextCursor, "End", None)
            if end_op is None:
                end_op = QTextCursor.MoveOperation.End
            cursor.movePosition(end_op)
            self.log_text.setTextCursor(cursor)

        def _load_runtime_log_for_current_project(self):
            log_path = self._current_runtime_log_path()
            if log_path is None or not log_path.exists():
                self.runtime_log_buffer = []
                self._refresh_runtime_log_view()
                return
            try:
                self.runtime_log_buffer = log_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                self.runtime_log_buffer = []
            self._refresh_runtime_log_view()

        def clear_runtime_log_view(self):
            self.runtime_log_buffer.clear()
            self._refresh_runtime_log_view()
            self._set_status("日志界面已清空")

        def reload_runtime_log_from_disk(self):
            log_path = self._current_runtime_log_path()
            if log_path is None or not log_path.exists():
                QMessageBox.information(self, "提示", "当前项目还没有运行日志文件。")
                return
            try:
                self.runtime_log_buffer = log_path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                QMessageBox.critical(self, "读取失败", f"读取日志失败：\n{exc}")
                return
            self._refresh_runtime_log_view()
            self._set_status("已从磁盘重载运行日志")

        def export_runtime_log_copy(self):
            project_dir = self._project_dir_for_mode()
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            export_path = project_dir / "logs" / f"runtime_export_{datetime.now():%Y%m%d_%H%M%S}.log"
            export_path.write_text("\n".join(self.runtime_log_buffer) + ("\n" if self.runtime_log_buffer else ""), encoding="utf-8")
            self._append_log(f"日志副本已导出: {export_path}")
            QMessageBox.information(self, "导出完成", f"日志副本已导出到：\n{export_path}")

        def open_log_dir(self):
            project_dir = self._project_dir_for_mode()
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            log_dir = project_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
            self._append_log(f"打开日志目录: {log_dir}")

        def detect_device(self, auto: bool = False, silent: bool = False):
            if self._auto_detect_device_running:
                return
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                return
            self._auto_detect_device_running = True
            if not auto:
                self._set_task_state("capture", "running")
                self._set_status("正在检测设备...")

            def worker():
                ok_profile, profile_or_error = safe_get_device_profile()
                if not ok_profile:
                    self.bridge.device_detected_signal.emit({}, False, str(profile_or_error), silent)
                    return

                profile = dict(profile_or_error)
                ok_res, resolution_or_error = safe_get_screen_resolution()
                if ok_res:
                    w, h = resolution_or_error
                    profile["resolution"] = [w, h]
                else:
                    profile["resolution_error"] = str(resolution_or_error)
                self.bridge.device_detected_signal.emit(profile, True, "", silent)

            threading.Thread(target=worker, daemon=True).start()

        def _apply_detected_device_result(self, profile: dict, success: bool, error_text: str, silent: bool):
            self._auto_detect_device_running = False
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                self._set_task_state("capture", "idle")
                return
            if not success:
                for bundle in (self.capture_fields, self.record_fields, self.longshot_fields):
                    bundle.device.setText("未检测到设备")
                self.device_info = {}
                if not silent:
                    self._append_log(f"设备检测失败：{error_text}")
                    QMessageBox.critical(self, "检测设备失败", error_text)
                    self._set_status("设备检测失败")
                self._set_task_state("capture", "idle")
                return

            old_folder = (self.device_info or {}).get("folder_name", "")
            old_resolution = (self.device_info or {}).get("resolution")
            self.device_info = dict(profile)
            base_text = profile.get("display_name") or profile.get("device_id") or "Android"
            resolution = profile.get("resolution")
            resolution_error = profile.get("resolution_error", "")
            if isinstance(resolution, (list, tuple)) and len(resolution) == 2:
                device_text = f"{base_text} ({resolution[0]}x{resolution[1]})"
                if not silent and (old_folder != (profile.get("folder_name") or "") or old_resolution != resolution):
                    self._append_log(f"检测到设备: {base_text}, 分辨率: {resolution[0]}x{resolution[1]}")
            else:
                device_text = base_text
                if resolution_error and not silent and (old_folder != (profile.get("folder_name") or "") or old_resolution != resolution):
                    self._append_log(f"检测到设备: {base_text}，但分辨率获取失败：{resolution_error}")

            for bundle in (self.capture_fields, self.record_fields, self.longshot_fields):
                bundle.device.setText(device_text)

            if (profile.get("folder_name") or "") != old_folder or old_resolution != profile.get("resolution"):
                self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            if not silent:
                self._set_status("设备检测完成")
            self._set_task_state("capture", "idle")

        def detect_app(self, auto: bool = False, silent: bool = False):
            if self._auto_detect_app_running:
                return
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                return
            self._auto_detect_app_running = True
            if not auto:
                self._set_task_state("capture", "running")
                self._set_status("正在检测 App...")

            def worker():
                ok, info_or_error = safe_get_current_app()
                if not ok:
                    self.bridge.app_detected_signal.emit({}, False, str(info_or_error), silent, auto)
                    return
                self.bridge.app_detected_signal.emit(dict(info_or_error), True, "", silent, auto)

            threading.Thread(target=worker, daemon=True).start()

        def _apply_detected_app_result(self, info: dict, success: bool, error_text: str, silent: bool, auto: bool):
            self._auto_detect_app_running = False
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                self._set_task_state("capture", "idle")
                return
            if not success:
                if not silent:
                    self._append_log(f"App 检测失败：{error_text}")
                    QMessageBox.critical(self, "检测 App 失败", error_text)
                    self._set_status("App 检测失败")
                self._set_task_state("capture", "idle")
                return

            changed = self._apply_detected_app_info(info, log_change=not silent)
            if changed:
                self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            if not silent:
                self._set_status("App 检测完成")
            self._set_task_state("capture", "idle")

        def detect_title(self):
            self._set_task_state(self.current_context_kind, "running")
            self._set_status("正在识别标题...")
            ok_title, title_or_error = safe_get_chat_title()
            if ok_title:
                title = str(title_or_error).strip()
            else:
                title = ""
                self._append_log(f"自动识别标题失败：{title_or_error}")

            if self.current_context_kind == "record":
                target_bundle = self.record_fields
            elif self.current_context_kind == "longshot":
                target_bundle = self.longshot_fields
            else:
                target_bundle = self.capture_fields

            preserve_custom_name = self._should_preserve_custom_session_name(target_bundle)

            if title:
                new_title, ok = QInputDialog.getText(self, "确认聊天标题", "自动识别到标题，请确认或修改：", text=title)
                final_title = new_title.strip() if ok and new_title.strip() else title
                target_bundle.chat_title.setText(final_title)
                if not preserve_custom_name:
                    target_bundle.session_name.setText(sanitize_name(final_title))
                self._append_log(f"识别到聊天标题({self.current_context_kind}): {final_title}")
            else:
                manual, ok = QInputDialog.getText(self, "手动输入标题", "请输入聊天标题（对方昵称/群名）：")
                if ok and manual.strip():
                    final_title = manual.strip()
                    target_bundle.chat_title.setText(final_title)
                    if not preserve_custom_name:
                        target_bundle.session_name.setText(sanitize_name(final_title))
                    self._append_log(f"手动设置聊天标题({self.current_context_kind}): {final_title}")
                else:
                    QMessageBox.information(self, "提示", "未输入标题，已保持原值。")
                    self._set_task_state(self.current_context_kind, "idle")
                    return
            self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            self._set_task_state(self.current_context_kind, "idle")

        def choose_output_root(self):
            selected = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.capture_fields.project_root.text() or CONFIG["output_root"])
            if selected:
                CONFIG["output_root"] = selected
                for bundle in (self.capture_fields, self.record_fields, self.longshot_fields):
                    bundle.project_root.setText(selected)
                self._append_log(f"输出根目录已设置为: {selected}")
                self.refresh_project(silent=True, mode_kind=self.current_context_kind)

        def _apply_detected_app_info(self, info: dict, log_change: bool = False) -> bool:
            package = str(info.get("package", "")).strip()
            app_name = str(info.get("app_name", "")).strip() or "UnknownApp"
            if not package:
                return False

            old_package = self._last_auto_app_package
            old_app_name = str((self.app_info or {}).get("app_name", "")).strip()
            changed = package != old_package or app_name != old_app_name
            self.app_info = {"package": package, "app_name": app_name}
            for bundle in (self.capture_fields, self.record_fields, self.longshot_fields):
                bundle.app_name.setText(app_name)
                bundle.package.setText(package)

            if changed:
                self._last_auto_app_package = package
            if changed and log_change:
                self._append_log(f"检测到 App: {app_name} / {package}")
            return changed

        def _active_fields(self, mode_kind: str | None = None) -> FieldBundle:
            if mode_kind == "record":
                return self.record_fields
            if mode_kind == "longshot":
                return self.longshot_fields
            if mode_kind == "capture":
                return self.capture_fields
            current_index = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
            if current_index == 1:
                return self.record_fields
            if current_index == 2:
                return self.longshot_fields
            return self.capture_fields

        def _default_session_name(self, fields: FieldBundle, fallback_prefix: str = "session") -> str:
            chat_title = fields.chat_title.text().strip()
            if chat_title and chat_title != "未识别":
                return sanitize_name(chat_title)
            return sanitize_name(f"{fallback_prefix}_{datetime.now():%Y%m%d_%H%M%S}")

        def _sync_session_name_with_custom_toggle(self, fields: FieldBundle, checked: bool, fallback_prefix: str = "session"):
            if checked:
                return
            fields.session_name.setText(self._default_session_name(fields, fallback_prefix))

        def _should_preserve_custom_session_name(self, fields: FieldBundle) -> bool:
            checkbox = getattr(fields, "custom_name_checkbox", None)
            if checkbox is None or not checkbox.isChecked():
                return False
            return bool(fields.session_name.text().strip())

        def _build_project_dir(self, mode_kind: str | None = None) -> Path:
            normalized_mode = mode_kind or self.current_context_kind or "capture"
            fields = self._active_fields(normalized_mode if normalized_mode in {"capture", "record", "longshot"} else "capture")
            app_name = fields.app_name.text().strip() or self.app_info.get("app_name", "") or "UnknownApp"
            package = fields.package.text().strip() or self.app_info.get("package", "") or "unknown.package"
            device_folder = (self.device_info or {}).get("folder_name") or "UnknownDevice"
            root_dir = Path(fields.project_root.text())
            device_dir = root_dir / sanitize_name(device_folder)
            if normalized_mode == "app":
                return device_dir / "App导出"
            base_dir = device_dir / sanitize_name(f"{app_name}_{package}")
            suffix_map = {
                "capture": "capture",
                "record": "record",
                "longshot": "longshot",
            }
            return base_dir / suffix_map.get(normalized_mode, "capture")

        def _project_dir_for_mode(self, mode_kind: str | None = None) -> Path | None:
            normalized_mode = mode_kind or self.current_context_kind or "capture"
            if normalized_mode == "record":
                return self.record_project_dir
            if normalized_mode == "longshot":
                return self.longshot_project_dir
            if normalized_mode == "app":
                return self.app_project_dir
            return self.capture_project_dir

        def _capturer_for_mode(self, mode_kind: str | None = None) -> ScreenCapture | None:
            normalized_mode = mode_kind or self.current_context_kind or "capture"
            if normalized_mode == "record":
                return self.record_capturer
            if normalized_mode == "longshot":
                return self.longshot_capturer
            return self.capture_capturer

        def refresh_project(self, silent: bool = False, mode_kind: str | None = None):
            normalized_mode = mode_kind or self.current_context_kind or "capture"
            if not hasattr(self, "capture_fields") or not hasattr(self, "record_fields") or not hasattr(self, "longshot_fields"):
                self.current_context_kind = normalized_mode
                return None
            if normalized_mode == "record":
                source_fields = self.record_fields
            elif normalized_mode == "longshot":
                source_fields = self.longshot_fields
            elif normalized_mode == "capture":
                source_fields = self.capture_fields
            else:
                source_fields = self._active_fields(self.current_context_kind)
            self._sync_shared_fields(source_fields)
            project_dir = self._build_project_dir(normalized_mode)
            project_signature = f"{normalized_mode}:{project_dir}"
            if self._last_project_signature_by_mode.get(normalized_mode) == project_signature and self._project_dir_for_mode(normalized_mode) == project_dir:
                self.current_context_kind = normalized_mode
                self.project_dir = project_dir
                return project_dir
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "logs").mkdir(exist_ok=True)
            self.current_context_kind = normalized_mode
            self.project_dir = project_dir

            existing_project_dir = self._project_dir_for_mode(normalized_mode)
            existing_capturer = self._capturer_for_mode(normalized_mode)
            capturer = existing_capturer if existing_project_dir == project_dir else None
            if normalized_mode in {"capture", "record", "longshot"}:
                if capturer is None:
                    try:
                        capturer = ScreenCapture(project_dir)
                    except Exception as exc:
                        if normalized_mode == "capture":
                            self.capture_capturer = None
                        elif normalized_mode == "record":
                            self.record_capturer = None
                        else:
                            self.longshot_capturer = None
                        self.capturer = None
                        if not silent:
                            self._append_log(f"项目已创建，但采集器初始化失败：{format_adb_error(exc)}")
                    else:
                        self.capturer = capturer
                else:
                    self.capturer = capturer

                if capturer is not None:
                    if normalized_mode == "capture":
                        self.capture_capturer = capturer
                        self.capture_project_dir = project_dir
                    elif normalized_mode == "record":
                        self.record_capturer = capturer
                        self.record_project_dir = project_dir
                    else:
                        self.longshot_capturer = capturer
                        self.longshot_project_dir = project_dir
            else:
                self.app_project_dir = project_dir

            if normalized_mode == "capture":
                self.capture_project_dir = project_dir
            elif normalized_mode == "record":
                self.record_project_dir = project_dir
            elif normalized_mode == "longshot":
                self.longshot_project_dir = project_dir
            elif normalized_mode == "app":
                self.app_project_dir = project_dir

            self._last_project_signature_by_mode[normalized_mode] = project_signature
            self._load_runtime_log_for_current_project()
            if not silent:
                self._append_log(f"项目目录已创建: {project_dir}")
            return project_dir

        def open_project_dir(self):
            project_dir = self._project_dir_for_mode()
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=self.current_context_kind)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(project_dir)))
            self._append_log(f"打开目录: {project_dir}")

        def _ensure_mode_context(self, mode_kind: str) -> tuple[Path | None, ScreenCapture | None, FieldBundle]:
            project_dir = self._switch_context(mode_kind, load_log=True)
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=mode_kind)
            capturer = self._capturer_for_mode(mode_kind)
            fields = self._active_fields(mode_kind)
            return project_dir, capturer, fields

        def _resolve_session_name(self, fields: FieldBundle, fallback_prefix: str, allow_custom: bool = False) -> str | None:
            session_text = fields.session_name.text().strip()
            chat_title = fields.chat_title.text().strip()
            should_use_custom = bool(allow_custom and fields.custom_name_checkbox and fields.custom_name_checkbox.isChecked())
            if should_use_custom:
                default_text = session_text or sanitize_name(chat_title) or sanitize_name(fallback_prefix)
                custom_text, ok = QInputDialog.getText(
                    self,
                    "自定义命名",
                    "请输入本次输出名称：",
                    text=default_text,
                )
                if not ok:
                    self._append_log("已取消自定义命名，本次不修改名称")
                    return None
                custom_text = custom_text.strip()
                if not custom_text:
                    QMessageBox.information(self, "名称为空", "未输入自定义名称，本次不修改名称。")
                    return None
                sanitized = sanitize_name(custom_text)
                if not sanitized:
                    QMessageBox.warning(self, "名称无效", "自定义名称无效，本次不修改名称。")
                    return None
                fields.session_name.setText(sanitized)
                return sanitized
            if session_text:
                return sanitize_name(session_text)
            if chat_title:
                sanitized_title = sanitize_name(chat_title)
                fields.session_name.setText(sanitized_title)
                return sanitized_title
            generated = sanitize_name(f"{fallback_prefix}_{datetime.now():%Y%m%d_%H%M%S}")
            fields.session_name.setText(generated)
            return generated

        def _run_capture_task(self, kind: str, title: str, worker_fn):
            if self.current_task_state in {"running", "stopping"}:
                QMessageBox.information(self, "任务进行中", "当前已有任务正在执行，请先停止或等待完成。")
                return

            project_dir = self._project_dir_for_mode(kind)
            if project_dir is None:
                project_dir = self.refresh_project(silent=True, mode_kind=kind)
            if project_dir is None:
                QMessageBox.warning(self, "项目初始化失败", "无法创建当前模式的项目目录。")
                return

            self.stop_event.clear()
            self.current_context_kind = kind
            self._set_task_state(kind, "running")
            self._set_status(title)
            self._append_log(title)

            def worker_wrapper():
                final_state = "idle"
                final_status = f"{title}完成"
                try:
                    worker_fn()
                    if self.stop_event.is_set():
                        final_status = f"{title}已停止"
                    else:
                        final_status = f"{title}完成"
                except Exception as exc:
                    final_state = "failed"
                    final_status = f"{title}失败"
                    self._append_log(f"{title}异常：{format_adb_error(exc)}")
                finally:
                    self.worker = None
                    self._set_task_state(kind, final_state)
                    self._set_status(final_status)
                    self.stop_event.clear()

            self.worker = threading.Thread(target=worker_wrapper, daemon=True)
            self.worker.start()

        def start_screenshot(self):
            project_dir, capturer, fields = self._ensure_mode_context("capture")
            if project_dir is None or capturer is None:
                QMessageBox.warning(self, "截图不可用", "截图项目或采集器初始化失败，请先检查设备连接。")
                return

            mode = self._selected_mode("capture")
            session_name = self._resolve_session_name(fields, "capture", allow_custom=(mode == 2))
            if not session_name:
                return

            def worker():
                if mode == 2:
                    self._append_log(f"截图模式2开始：手动单张截图 -> {session_name}")
                    output_path = capturer.manual_capture(session_name)
                    if output_path:
                        self._append_log(f"手动截图已保存：{output_path}")
                    else:
                        raise RuntimeError("手动截图失败")
                    return

                if mode == 4:
                    self._append_log(f"截图模式4开始：重点内容识别 -> {session_name}")
                    count, output_path = capturer.important_capture_and_crop(
                        session_name,
                        stop_event=self.stop_event,
                        status_cb=self._append_log,
                        skip_initial_seek=False,
                    )
                    self._append_log(f"重点内容截图结束：共保存 {count} 张，输出={output_path or '无'}")
                    return

                skip_initial_seek = mode == 3
                self._append_log(
                    f"截图任务开始：模式{mode} · 会话={session_name} · 项目={project_dir}"
                )
                count = capturer.auto_capture_with_scroll(
                    session_name,
                    mode="down",
                    stop_event=self.stop_event,
                    status_cb=self._append_log,
                    skip_initial_seek=skip_initial_seek,
                )
                self._append_log(f"截图任务结束：共保存 {count} 张")

                if count > 0 and not self.stop_event.is_set():
                    self._set_status("正在查询是否有 APK 或网址...")
                    self._append_log("正在查询是否有apk或网址...")
                    try:
                        scan_result = capturer.scan_session_for_apk_and_links(session_name)
                        if scan_result.get("apk") or scan_result.get("link"):
                            chat_dir = project_dir / session_name
                            self._append_log("查询到 APK 或网址，正在展示截图位置...")
                            self.bridge.resource_found_signal.emit(scan_result, str(chat_dir))
                        else:
                            self._append_log("查询完成：未发现 APK 或网址")
                            self.bridge.resource_scan_empty_signal.emit("未识别出 APK 或网址，请根据实际情况甑别。")
                    except Exception as exc:
                        self._append_log(f"查询异常：{exc}")
                        self.bridge.resource_scan_empty_signal.emit(f"查询异常：{exc}")

            if mode == 2:
                status_text = "正在执行手动截图..."
            elif mode == 4:
                status_text = "正在执行重点内容截图..."
            else:
                status_text = "正在执行截图任务..."
            self._run_capture_task("capture", status_text, worker)

        def stop_screenshot(self):
            if self.current_task_kind != "capture" or self.current_task_state not in {"running", "stopping"}:
                return
            self.stop_event.set()
            self._set_task_state("capture", "stopping")
            self._set_status("正在停止截图任务...")
            self._append_log("收到停止截图请求")

        def start_recording(self):
            project_dir, capturer, fields = self._ensure_mode_context("record")
            if project_dir is None or capturer is None:
                QMessageBox.warning(self, "录屏不可用", "录屏项目或采集器初始化失败，请先检查设备连接。")
                return

            mode = self._selected_mode("record")
            session_name = self._resolve_session_name(fields, "record", allow_custom=(mode == 2))
            if not session_name:
                return

            def worker():
                self._append_log(f"录屏任务开始：模式{mode} · 会话={session_name} · 项目={project_dir}")
                if mode == 1:
                    self._append_log("录屏模式1：先快速滚动到顶部")
                    capturer.scroll_to_top(stop_event=self.stop_event)
                    if self.stop_event.is_set():
                        self._append_log("录屏模式1在顶部定位阶段被停止")
                        return
                    self._append_log("录屏模式1已到顶部，开始直接录制，不做额外到底验证等待")
                    result = capturer.record_session(
                        session_name,
                        stop_event=self.stop_event,
                        auto_swipe=True,
                        swipe_direction="up",
                        status_cb=self._append_log,
                    )
                elif mode == 2:
                    result = capturer.record_session(
                        session_name,
                        stop_event=self.stop_event,
                        auto_swipe=False,
                        status_cb=self._append_log,
                    )
                else:
                    self._append_log("录屏模式3：从当前位置直接录制，不做额外到底验证等待")
                    result = capturer.record_session(
                        session_name,
                        stop_event=self.stop_event,
                        auto_swipe=True,
                        swipe_direction="up",
                        status_cb=self._append_log,
                    )
                self._append_log(f"录屏任务结束：导出结果={result}")

            self._run_capture_task("record", "正在执行录屏任务...", worker)

        def stop_recording(self):
            if self.current_task_kind != "record" or self.current_task_state not in {"running", "stopping"}:
                return
            self.stop_event.set()
            self._set_task_state("record", "stopping")
            self._set_status("正在停止录屏任务...")
            self._append_log("收到停止录屏请求")

        def start_longshot(self):
            project_dir, capturer, fields = self._ensure_mode_context("longshot")
            if project_dir is None or capturer is None:
                QMessageBox.warning(self, "长截图不可用", "长截图项目或采集器初始化失败，请先检查设备连接。")
                return

            mode = self._selected_mode("longshot")
            session_name = self._resolve_session_name(fields, "longshot", allow_custom=(mode == 2))
            if not session_name:
                return

            def worker():
                self._append_log(f"长截图任务开始：模式{mode} · 会话={session_name} · 项目={project_dir}")
                count, output_path = capturer.longshot_capture_and_stitch(
                    session_name,
                    mode=mode,
                    stop_event=self.stop_event,
                    status_cb=self._append_log,
                )
                self._append_log(f"长截图任务结束：抓取 {count} 张，输出={output_path or '无'}")

            self._run_capture_task("longshot", "正在执行长截图任务...", worker)

        def stop_longshot(self):
            if self.current_task_kind != "longshot" or self.current_task_state not in {"running", "stopping"}:
                return
            self.stop_event.set()
            self._set_task_state("longshot", "stopping")
            self._set_status("正在停止长截图任务...")
            self._append_log("收到停止长截图请求")

        def refresh_app_list(self):
            if self.app_refreshing:
                return
            self.app_refreshing = True
            self.current_context_kind = "app"
            self._set_task_state("app", "running")
            self._set_status("正在刷新 App 列表...")
            self._append_log("开始刷新 App 列表")
            include_system = self.include_system_checkbox.isChecked()

            def worker():
                try:
                    ok, items_or_error = safe_list_installed_apps(include_system=include_system)
                    if ok:
                        self.bridge.app_list_signal.emit(items_or_error)
                    else:
                        self.bridge.app_error_signal.emit(str(items_or_error))
                finally:
                    self.bridge.app_refresh_done_signal.emit()

            threading.Thread(target=worker, daemon=True).start()

        def _apply_app_list(self, items: list[dict]):
            self.app_items = items
            self.app_page = 0
            self.app_selected_packages.intersection_update({app["package"] for app in items})
            self._render_app_page()
            self._append_log(f"App 列表已刷新，共 {len(self.app_items)} 项")

        def _on_app_list_error(self, error_text: str):
            self.current_context_kind = "app"
            self._set_task_state("app", "failed")
            self._append_log(f"App 列表刷新失败：{error_text}")
            QMessageBox.critical(self, "App 列表刷新失败", error_text)

        def _finish_app_refresh(self):
            self.app_refreshing = False
            self.current_context_kind = "app"
            if self.current_task_kind == "app" and self.current_task_state != "failed":
                self._set_task_state("app", "idle")
            self._set_status("App 列表已就绪")
            self._append_log("App 列表刷新完成")

        def _filtered_app_items(self) -> list[dict]:
            keyword = self.app_filter_text.strip().lower()
            if not keyword:
                return list(self.app_items)
            return [
                app for app in self.app_items
                if keyword in str(app.get("name", "")).lower()
                or keyword in str(app.get("package", "")).lower()
                or keyword in str(app.get("source", "")).lower()
            ]

        def _on_app_filter_changed(self, text: str):
            self.app_filter_text = text.strip()
            self.app_page = 0
            self._render_app_page()

        def _current_page_apps(self) -> list[dict]:
            filtered = self._filtered_app_items()
            start = self.app_page * self.app_page_size
            end = start + self.app_page_size
            return filtered[start:end]

        def _toggle_package_selected(self, package: str, checked: bool):
            if checked:
                self.app_selected_packages.add(package)
            else:
                self.app_selected_packages.discard(package)
            self._sync_app_row_checkbox(package)
            self._update_app_summary_labels()

        def _sync_app_row_checkbox(self, package: str):
            for row in range(self.app_table.rowCount()):
                cell = self.app_table.cellWidget(row, 0)
                if cell is None:
                    continue
                checkbox = cell.findChild(QCheckBox)
                row_package_item = self.app_table.item(row, 2)
                if checkbox is None or row_package_item is None:
                    continue
                if row_package_item.text() != package:
                    continue
                blocked = checkbox.blockSignals(True)
                checkbox.setChecked(package in self.app_selected_packages)
                checkbox.blockSignals(blocked)
                break

        def _update_app_summary_labels(self):
            filtered_items = self._filtered_app_items()
            total = len(filtered_items)
            total_pages = max(1, (total + self.app_page_size - 1) // self.app_page_size)
            self.app_page = min(self.app_page, total_pages - 1)
            if hasattr(self, "app_stats_label"):
                self.app_stats_label.setText(
                    f"App 概览：{len(self.app_items)} 项 · 已选 {len(self.app_selected_packages)} 项 · 第 {self.app_page + 1}/{total_pages} 页"
                )
            self.app_page_label.setText(
                f"第 {self.app_page + 1}/{total_pages} 页 · 每页 {self.app_page_size} 项 · 共 {total} 项 · 已选 {len(self.app_selected_packages)} 项"
            )
            self.app_filter_summary_label.setText(
                f"筛选结果：{len(filtered_items)} / {len(self.app_items)} 项"
                + (f" · 关键词：{self.app_filter_text}" if self.app_filter_text else "")
            )

        def _render_app_page(self):
            filtered_items = self._filtered_app_items()
            rows = self._current_page_apps()
            total = len(filtered_items)
            total_pages = max(1, (total + self.app_page_size - 1) // self.app_page_size)
            self.app_page = min(self.app_page, total_pages - 1)
            rows = self._current_page_apps()

            self.app_table.setRowCount(len(rows))
            for row, app in enumerate(rows):
                checkbox = QCheckBox()
                checkbox.setChecked(app["package"] in self.app_selected_packages)
                checkbox.stateChanged.connect(lambda state, pkg=app["package"]: self._toggle_package_selected(pkg, state == self._qt_checked_value()))
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(8, 0, 8, 0)
                cell_layout.addWidget(checkbox)
                cell_layout.setAlignment(self._qt_align_center())
                self.app_table.setCellWidget(row, 0, cell)

                for col, key in [(1, "name"), (2, "package"), (3, "source")]:
                    item = QTableWidgetItem(str(app.get(key, "")))
                    item.setFlags(item.flags() & ~self._qt_item_is_editable_flag())
                    self.app_table.setItem(row, col, item)

                export_btn = self._make_button("导出", lambda _=False, pkg=app["package"]: self.export_single_app(pkg), role="primary")
                export_btn.setToolTip(str(app.get("package", "")))
                # Center align the button in the cell
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.setContentsMargins(4, 2, 4, 2)
                btn_layout.addWidget(export_btn)
                btn_layout.setAlignment(self._qt_align_center())
                self.app_table.setCellWidget(row, 4, btn_container)
                self.app_table.setRowHeight(row, 42)

            self.app_page_label.setText(
                f"第 {self.app_page + 1}/{total_pages} 页 · 每页 {self.app_page_size} 项 · 共 {total} 项 · 已选 {len(self.app_selected_packages)} 项"
            )
            self.app_filter_summary_label.setText(
                f"筛选结果：{len(filtered_items)} / {len(self.app_items)} 项"
                + (f" · 关键词：{self.app_filter_text}" if self.app_filter_text else "")
            )

        def app_prev_page(self):
            if self.app_page > 0:
                self.app_page -= 1
                self._render_app_page()

        def app_next_page(self):
            total_pages = max(1, (len(self._filtered_app_items()) + self.app_page_size - 1) // self.app_page_size)
            if self.app_page + 1 < total_pages:
                self.app_page += 1
                self._render_app_page()

        def change_app_page_size(self, value: str):
            self.app_page_size = max(10, min(30, int(value or "10")))
            self.app_page = 0
            self._render_app_page()

        def open_app_export_dir(self):
            project_dir = self._switch_context("app", load_log=True)
            if project_dir is None:
                return
            export_dir = project_dir / "apks"
            export_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_dir)))
            self._append_log(f"打开 App 导出目录: {export_dir}")

        def export_single_app(self, package: str):
            app = next((item for item in self.app_items if item["package"] == package), None)
            display_name = app["name"] if app else package
            self._start_apk_export([package], f"单个导出 · {display_name}")

        def _start_apk_export(self, packages: list[str], source_label: str):
            if self.app_exporting:
                return
            package_list = [pkg for pkg in packages if pkg]
            if not package_list:
                QMessageBox.information(self, "未选择 App", "当前没有可导出的 App。")
                return

            project_dir = self._switch_context("app", load_log=True)
            if project_dir is None:
                return
            
            # 弹出目录选择对话框
            default_dir = str(project_dir / "apks")
            selected_dir = QFileDialog.getExistingDirectory(self, "选择APK保存目录", default_dir)
            if not selected_dir:
                return  # 用户取消选择
            export_dir = Path(selected_dir)
            export_dir.mkdir(parents=True, exist_ok=True)

            self.app_exporting = True
            self.current_context_kind = "app"
            self._set_task_state("app", "running")
            self._set_status(f"正在导出 {len(package_list)} 个 App...")
            self._append_log(f"开始导出 APK（{source_label}），共 {len(package_list)} 项 → {export_dir}")

            def worker():
                success_messages: list[str] = []
                failed_messages: list[str] = []
                try:
                    for package in package_list:
                        app = next((item for item in self.app_items if item.get("package") == package), {})
                        app_name = str(app.get("name", "")).strip() or None
                        ok, result = safe_export_package_apks(package, export_dir, app_name=app_name)
                        if ok:
                            success_messages.append(f"{package} -> {result}")
                        else:
                            failed_messages.append(f"{package} -> {result}")
                    self.bridge.apk_export_success_signal.emit(success_messages, failed_messages)
                except Exception as exc:
                    self.bridge.apk_export_error_signal.emit(format_adb_error(exc))
                finally:
                    self.bridge.apk_export_done_signal.emit()

            threading.Thread(target=worker, daemon=True).start()

        def export_selected_apps(self):
            selected_packages = sorted(self.app_selected_packages)
            if not selected_packages:
                QMessageBox.information(self, "未选择 App", "请先勾选要导出的 App。")
                return
            self._start_apk_export(selected_packages, "勾选项")

        def _after_apk_export_success(self, success_messages: list, failed_messages: list):
            self.current_context_kind = "app"
            if failed_messages:
                self._set_task_state("app", "failed")
                self._set_status("APK 导出部分完成")
            else:
                self._set_task_state("app", "idle")
                self._set_status("APK 导出完成")
            for item in success_messages:
                self._append_log(f"导出成功: {item}")
            for item in failed_messages:
                self._append_log(f"导出失败: {item}")
            summary = f"成功 {len(success_messages)} 项"
            if failed_messages:
                summary += f"，失败 {len(failed_messages)} 项"
            QMessageBox.information(self, "APK 导出结果", summary)

        def _after_apk_export_error(self, error_text: str):
            self.current_context_kind = "app"
            self._set_task_state("app", "failed")
            self._set_status("APK 导出异常")
            self._append_log(f"APK 导出异常: {error_text}")
            QMessageBox.critical(self, "APK 导出异常", error_text)

        def _finish_apk_export(self):
            self.app_exporting = False
            if self.current_task_kind == "app" and self.current_task_state == "running":
                self._set_task_state("app", "idle")
            if self.current_task_state != "failed":
                self._set_status("App 导出已就绪")

        def _show_resource_empty_dialog(self, message: str):
            """查询未发现内容时给出明确提示。"""
            self._append_log(f"【查询结果】{message}")
            QMessageBox.information(self, "查询结果", message)

        def _show_resource_found_dialog(self, result: dict, folder_path: str):
            """识别到 APK/网址时，展示对应截图位置；未识别到时给出明确提示。"""
            apk_list = result.get("apk", [])
            link_list = result.get("link", [])
            apk_details = result.get("apk_details", [])
            link_details = result.get("link_details", [])

            if not apk_list and not link_list:
                QMessageBox.information(self, "识别结果", "未识别出 APK 或网址，请根据实际情况甑别。")
                return

            details = list(apk_details) + list(link_details)
            if not details:
                QMessageBox.information(self, "识别结果", "未识别出 APK 或网址，请根据实际情况甑别。")
                return

            dialog = ScreenshotLocationDialog(self, folder_path, details, title="检测到 APK / 网址")
            dialog.exec()

            # 构建详细信息文本（直接展示）
            content_lines: list[str] = []
            if apk_list:
                content_lines.append(f"【APK 安装包】（{len(apk_list)} 个）")
                for item in apk_details:
                    content_lines.append(f"  • {item['value']}（{item['file']}）")
            if link_list:
                content_lines.append(f"【网址链接】（{len(link_list)} 个）")
                for item in link_details:
                    content_lines.append(f"  • {item['value']}（{item['file']}）")
            
            content_text = "\n".join(content_lines)

            # 同时在运行日志中输出
            self._append_log("=" * 40)
            self._append_log("【重要内容提醒】")
            for line in content_lines:
                self._append_log(line)
            self._append_log("=" * 40)

            msg = QMessageBox(self)
            msg.setWindowTitle("发现重要内容")
            msg.setIcon(QMessageBox.Icon.Information)
            
            # 构建提示文本（包含提示可在运行日志中查看）
            summary_parts = []
            if apk_list:
                summary_parts.append(f"APK 安装包 {len(apk_list)} 个")
            if link_list:
                summary_parts.append(f"网址链接 {len(link_list)} 个")
            
            full_text = f"在本次截图中检测到：{'，'.join(summary_parts)}。\n\n{content_text}\n\n（可在运行日志中查看）"
            msg.setText(full_text)

            # 只保留关闭按钮
            close_btn = msg.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(close_btn)

            msg.exec()

    class ScreenshotLocationDialog(QDialog):
        """显示截图并标注 APK/网址位置的对话框"""

        def __init__(self, parent, folder_path: str, details: list, max_width: int = 800, title: str = ""):
            super().__init__(parent)
            self.folder_path = folder_path
            self.details = details
            self.max_width = max_width
            self.current_index = 0

            self.setWindowTitle(title if title else "查看 APK/网址 位置")
            self.setMinimumSize(600, 500)
            self.resize(900, 700)

            self._build_ui()
            self._load_current_item()

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(16, 16, 16, 16)

            # 信息标签
            self.info_label = QLabel()
            self.info_label.setWordWrap(True)
            self.info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #416a97;")
            layout.addWidget(self.info_label)

            # 图片滚动区域
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)

            self.image_label = QLabel()
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
            self.image_label.setStyleSheet("background: #f0f0f0; border: 1px solid #ccc;")
            scroll.setWidget(self.image_label)
            layout.addWidget(scroll, 1)

            # 导航按钮区域
            nav_layout = QHBoxLayout()

            self.prev_btn = QPushButton("← 上一个")
            self.prev_btn.setEnabled(False)
            self.prev_btn.clicked.connect(self._show_previous)

            self.next_btn = QPushButton("下一个 →")
            self.next_btn.clicked.connect(self._show_next)

            self.counter_label = QLabel()
            self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
            self.counter_label.setStyleSheet("font-size: 13px; color: #666;")

            nav_layout.addWidget(self.prev_btn)
            nav_layout.addWidget(self.counter_label, 1)
            nav_layout.addWidget(self.next_btn)

            layout.addLayout(nav_layout)

            # 底部按钮
            bottom_layout = QHBoxLayout()
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.accept)
            bottom_layout.addStretch(1)
            bottom_layout.addWidget(close_btn)
            layout.addLayout(bottom_layout)

        def _load_current_item(self):
            if not self.details or self.current_index >= len(self.details):
                self.info_label.setText("没有可显示的内容")
                return

            item = self.details[self.current_index]
            value = item.get("value", "")
            filename = item.get("file", "")
            box = item.get("box")  # (left, top, right, bottom)
            img_width = item.get("img_width", 0)
            img_height = item.get("img_height", 0)

            # 判断类型：根据value后缀或对话框标题判断
            kind = "网址"
            if value.lower().endswith(('.apk', '.apkm', '.xapk', '.zip', '.rar', '.7z')):
                kind = "APK"
            self.info_label.setText(f"【{kind}】{value}")

            # 加载图片
            img_path = Path(self.folder_path) / filename
            if not img_path.exists():
                self.image_label.setText(f"图片不存在: {filename}")
                self._update_nav_buttons()
                return

            # 加载原始图片
            pixmap = QPixmap(str(img_path))
            if pixmap.isNull():
                self.image_label.setText(f"无法加载图片: {filename}")
                self._update_nav_buttons()
                return

            # 计算缩放比例
            scale = 1.0
            if pixmap.width() > self.max_width:
                scale = self.max_width / pixmap.width()
                new_width = self.max_width
                new_height = int(pixmap.height() * scale)
                pixmap = pixmap.scaled(new_width, new_height, Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt, 'AspectRatioMode') else Qt.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation if hasattr(Qt, 'TransformationMode') else Qt.SmoothTransformation)

            # 在图片上绘制标注框
            if box and len(box) == 4:
                painter = QPainter(pixmap)
                pen = QPen(QColor(255, 0, 0))  # 红色
                pen.setWidth(3)
                painter.setPen(pen)

                # 计算缩放后的坐标
                left = int(box[0] * scale)
                top = int(box[1] * scale)
                right = int(box[2] * scale)
                bottom = int(box[3] * scale)

                # 绘制矩形框
                painter.drawRect(left, top, right - left, bottom - top)

                # 绘制标签背景
                label_text = value[:30]  # 截断过长的文本
                font = painter.font()
                font.setBold(True)
                font.setPointSize(10)
                painter.setFont(font)

                text_rect = painter.boundingRect(left, top - 22, right - left, 20, Qt.AlignmentFlag.AlignLeft if hasattr(Qt, 'AlignmentFlag') else Qt.AlignLeft, label_text)
                painter.fillRect(text_rect, QColor(255, 0, 0, 200))

                # 绘制标签文字
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter, label_text)

                painter.end()

            self.image_label.setPixmap(pixmap)
            self._update_nav_buttons()

        def _show_previous(self):
            if self.current_index > 0:
                self.current_index -= 1
                self._load_current_item()

        def _show_next(self):
            if self.current_index < len(self.details) - 1:
                self.current_index += 1
                self._load_current_item()

        def _update_nav_buttons(self):
            self.prev_btn.setEnabled(self.current_index > 0)
            self.next_btn.setEnabled(self.current_index < len(self.details) - 1)
            self.counter_label.setText(f"{self.current_index + 1} / {len(self.details)}")


    def has_graphical_display() -> bool:
        if sys.platform.startswith("win") or sys.platform == "darwin":
            return True
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


    def print_qt_runtime_hint():
        if QT_AVAILABLE:
            return
        print("⚠️  GUI 不可用，自动回退到 CLI。")
        if QT_IMPORT_ERROR:
            print(f"   {QT_IMPORT_ERROR}")


    def run_gui() -> int:
        app = QApplication(sys.argv)
        window = CaptureMainWindow()
        window.show()
        return app.exec()
else:
    def has_graphical_display() -> bool:
        return False

    def print_qt_runtime_hint():
        if QT_IMPORT_ERROR:
            print(f"⚠️  GUI 不可用：{QT_IMPORT_ERROR}")
        else:
            print("⚠️  GUI 不可用，自动回退到 CLI。")

    def run_gui() -> int:
        print_qt_runtime_hint()
        return 1


def run_cli() -> int:
    clear_screen()
    print_banner()
    project_dir, _, _ = setup_project()
    capturer = ScreenCapture(project_dir)
    while True:
        print("\n请选择模式：")
        print("  1. 截图模式")
        print("  2. 录屏模式")
        print("  3. 长截图模式")
        print("  4. 重点内容截图（APK / 链接 / 账号）")
        print("  0. 退出")
        choice = input("> ").strip()
        if choice == "1":
            start_chat_capture(project_dir, capturer)
        elif choice == "2":
            session_name = confirm_input("录屏会话名称", datetime.now().strftime("record_%Y%m%d_%H%M%S"))
            capturer.record_session(session_name)
        elif choice == "3":
            session_name = confirm_input("长截图会话名称", datetime.now().strftime("longshot_%Y%m%d_%H%M%S"))
            capturer.longshot_capture_and_stitch(session_name)
        elif choice == "4":
            start_important_capture(project_dir, capturer)
        elif choice == "0":
            return 0
        else:
            print("⚠️  无效选择")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatExtractor-Screenshot 主程序")
    parser.add_argument("--gui", action="store_true", help="优先启动 GUI")
    parser.add_argument("--cli", action="store_true", help="强制使用 CLI")
    return parser


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"❌ Python 版本过低，至少需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        return 1

    args = build_arg_parser().parse_args()
    if args.cli:
        return run_cli()
    if args.gui:
        if QT_AVAILABLE and has_graphical_display():
            return run_gui()
        print_qt_runtime_hint()
        return run_cli()
    if QT_AVAILABLE and has_graphical_display():
        return run_gui()
    print_qt_runtime_hint()
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
