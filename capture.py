"""截图采集器 - 自动滚动截图和手动截图"""

from __future__ import annotations

import importlib
import re
import time
from dataclasses import dataclass
from io import BytesIO
from datetime import datetime
from pathlib import Path

from PIL import Image

from config import CONFIG
from adb_utils import (
    get_screen_resolution,
    image_similarity,
    estimate_vertical_shift,
    run_adb,
    screenshot_hash,
    start_screen_record,
    stop_screen_record,
    swipe_down,
    swipe_up,
    take_screenshot,
    system_longshot_keywords,
    trigger_system_screenshot,
    try_fetch_latest_system_screenshot,
    try_tap_ui_keywords,
)


@dataclass
class OCRLine:
    text: str
    box: tuple[int, int, int, int]
    score: float = 0.0


IMPORTANT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("apk", re.compile(r"\b[\w.+-]+\.(?:apk|apkm|xapk|zip|rar|7z)\b", re.IGNORECASE)),
    ("link", re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)),
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b")),
    ("account", re.compile(r"\b(?:wxid_[a-zA-Z0-9_-]{5,}|uid[:：]?\s*\w+|id[:：]?\s*\w+|qq[:：]?\s*\d{5,}|v?x[:：]?\s*\w+)\b", re.IGNORECASE)),
]

IMPORTANT_KEYWORDS = (
    "apk",
    "安装包",
    "下载",
    "链接",
    "账号",
    "账户",
    "密码",
    "提取码",
    "验证码",
    "微信号",
    "wxid",
    "uid",
    "qq",
    "邮箱",
    "手机号",
)


class ScreenCapture:
    """截图采集器"""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screen_width, self.screen_height = get_screen_resolution()
        self._ocr_backend: str | None = None
        self._ocr_engine = None
        self._ocr_numpy = None
        self._tesseract_output = None

    def _sleep_interruptible(self, seconds: float, stop_event=None, step: float = 0.1) -> bool:
        """可被 stop_event 中断的睡眠"""
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            if stop_event and stop_event.is_set():
                return False
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
        return True

    def _current_swipe_down(self):
        return swipe_down(duration=CONFIG["swipe_duration"])

    def _current_swipe_up(self):
        return swipe_up(duration=CONFIG["swipe_duration"])

    def _quick_swipe_down(self):
        return swipe_down(duration=CONFIG["top_swipe_duration"])

    def _is_stable_boundary(self, motion: float, similarity: float) -> bool:
        """判定是否已稳定到顶/底，避免仅凭微小位移误判。"""
        return motion <= CONFIG["bottom_motion_threshold"] and similarity >= CONFIG["similarity_threshold"]

    def _resolve_output_name(self, text: str | None, fallback: str) -> str:
        value = (text or "").strip()
        if value:
            normalized = "".join(c if c.isalnum() or c in " ._-" else "_" for c in value).strip().replace(" ", "_")
            if normalized:
                return normalized
        return fallback

    def _find_next_index(self, directory: Path, prefix: str, suffix: str) -> int:
        if not directory.exists():
            return 1
        pattern = re.compile(rf"^{re.escape(prefix)}_(\d+){re.escape(suffix)}$")
        max_index = 0
        for item in directory.iterdir():
            if not item.is_file():
                continue
            match = pattern.match(item.name)
            if match:
                max_index = max(max_index, int(match.group(1)))
        return max_index + 1

    def prepare_capture_session_dir(self, session_name: str, overwrite: bool = False) -> tuple[Path, int]:
        chat_dir = self.output_dir / session_name
        chat_dir.mkdir(parents=True, exist_ok=True)
        start_index = 1
        if overwrite:
            for old_file in chat_dir.glob("*.png"):
                try:
                    old_file.unlink()
                except OSError:
                    pass
        else:
            start_index = self._find_next_index(chat_dir, session_name, ".png")
        return chat_dir, start_index

    def build_manual_capture_path(self, base_name: str | None = None) -> Path:
        manual_dir = self.output_dir / "手动截图"
        manual_dir.mkdir(parents=True, exist_ok=True)
        resolved_base = self._resolve_output_name(base_name, f"capture_manual_{datetime.now():%Y%m%d_%H%M%S}")
        next_index = self._find_next_index(manual_dir, resolved_base, ".png")
        return manual_dir / f"{resolved_base}_{next_index:03d}.png"

    def build_record_session_paths(self, session_name: str, overwrite: bool = False) -> tuple[Path, Path]:
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        video_path = session_dir / f"{session_name}.mp4"
        if overwrite:
            for old_file in session_dir.glob("*.mp4"):
                try:
                    old_file.unlink()
                except OSError:
                    pass
            return session_dir, video_path

        if not video_path.exists():
            return session_dir, video_path

        next_index = self._find_next_index(session_dir, session_name, ".mp4")
        return session_dir, session_dir / f"{session_name}_{next_index:03d}.mp4"

    def is_top_stable(self, reference_img: bytes | None = None, stop_event=None) -> bool:
        """判断当前是否已经稳定在聊天顶部。仅做一次快速探测，避免录屏启动前重复等待。"""
        baseline = reference_img or take_screenshot()
        if not baseline:
            return False
        if stop_event and stop_event.is_set():
            return False

        self._quick_swipe_down()
        if not self._sleep_interruptible(max(0.08, CONFIG["swipe_interval"] * 0.14), stop_event=stop_event):
            return False

        current = take_screenshot()
        if not current:
            return False
        motion = estimate_vertical_shift(baseline, current)
        sim = image_similarity(baseline, current)
        if self._is_stable_boundary(motion, sim):
            return True
        return sim >= CONFIG["top_detection_threshold"]

    def scroll_to_top(self, stop_event=None) -> int:
        """先滚动到聊天记录最顶端（最早的消息）。优先用静态相似度快速判顶，必要时才补一次轻量探测。"""
        print("\n⏫ 正在滚动到聊天记录顶部...")
        print("   （动态分辨率 + 相似度检测，避免状态栏误判）\n")

        scroll_count = 0
        stable_needed = max(1, CONFIG["top_stable_threshold"])
        stable_hits = 0
        motion_hits = 0
        last_img = None
        safety_limit = 180

        while scroll_count < safety_limit:
            if stop_event and stop_event.is_set():
                print("   ⏹️  已取消顶部查找")
                break

            img = take_screenshot()
            if not img:
                if not self._sleep_interruptible(0.08, stop_event=stop_event):
                    print("   ⏹️  已取消顶部查找")
                    break
                continue

            if last_img is not None:
                motion = estimate_vertical_shift(last_img, img)
                sim = image_similarity(last_img, img)
                if self._is_stable_boundary(motion, sim):
                    motion_hits += 1
                else:
                    motion_hits = 0
                if motion_hits >= CONFIG["bottom_motion_threshold_hits"]:
                    print(f"   ✅ 已到达最顶端（滚动了 {scroll_count} 次，位移={motion:.4f}）")
                    break

                if sim >= CONFIG["top_detection_threshold"]:
                    stable_hits += 1
                else:
                    stable_hits = 0
                if stable_hits >= stable_needed:
                    print(f"   ✅ 已到达最顶端（滚动了 {scroll_count} 次）")
                    break

            if last_img is not None and self.is_top_stable(reference_img=img, stop_event=stop_event):
                print(f"   ✅ 已到达最顶端（滚动了 {scroll_count} 次）")
                break

            last_img = img

            if stop_event and stop_event.is_set():
                print("   ⏹️  已取消顶部查找")
                break

            self._quick_swipe_down()
            scroll_count += 1
            if scroll_count % 10 == 0:
                print(f"   ⏫ 已滚动 {scroll_count} 次...")
            if not self._sleep_interruptible(max(0.08, CONFIG["swipe_interval"] * 0.14), stop_event=stop_event):
                print("   ⏹️  已取消顶部查找")
                break
        else:
            print("   ⚠️  顶部未能自动确认，已达到安全上限")

        self._sleep_interruptible(0.08, stop_event=stop_event)
        return scroll_count

    def auto_capture_with_scroll(
        self,
        chat_name: str,
        mode: str = "down",
        stop_event=None,
        status_cb=None,
        skip_initial_seek: bool = False,
        overwrite_existing: bool = False,
    ) -> int:
        """自动滚动截图（聊天记录）

        mode:
            down  - 向下截图（默认）
            up    - 自动找底部后，向上截图

        skip_initial_seek:
            False - down 模式下先自动找顶部
            True  - 直接从当前位置开始，不做顶部/底部预定位
        """

        def log(message: str):
            print(message)
            if status_cb:
                status_cb(message)

        if mode == "down":
            if not skip_initial_seek:
                self.scroll_to_top(stop_event=stop_event)
                if stop_event and stop_event.is_set():
                    log("   已停止")
                    return 0
            else:
                log("\n已跳过顶部查找，从当前位置直接开始截图")
        else:
            if not skip_initial_seek:
                log("\n正在尝试滚动到聊天底部...")
                for _ in range(20):
                    if stop_event and stop_event.is_set():
                        log("   已停止")
                        return 0
                    self._current_swipe_up()
                    if not self._sleep_interruptible(CONFIG["swipe_interval"] * 0.6, stop_event=stop_event):
                        log("   已停止")
                        return 0
            else:
                log("\n已跳过底部查找，从当前位置直接开始截图")

        log(f"\n开始截图采集: {chat_name}")
        log(f"   最大截图数: {CONFIG['max_screenshots']}")
        log("   按停止按钮可随时取消\n")

        chat_dir, next_index = self.prepare_capture_session_dir(chat_name, overwrite=overwrite_existing)

        seen_hashes: list[str] = []
        saved_count = 0
        repeat_count = 0
        prev_img: bytes | None = None
        bottom_motion_hits = 0

        try:
            while True:
                if stop_event and stop_event.is_set():
                    log("   已停止")
                    break

                img_bytes = take_screenshot()
                if not img_bytes:
                    log("   截图失败，重试...")
                    if not self._sleep_interruptible(0.4, stop_event=stop_event):
                        log("   已停止")
                        break
                    continue

                current_hash = screenshot_hash(img_bytes)
                duplicate = current_hash in seen_hashes
                motion = 1.0
                if prev_img is not None:
                    sim = image_similarity(prev_img, img_bytes)
                    duplicate = duplicate or sim >= CONFIG["similarity_threshold"]
                    motion = estimate_vertical_shift(prev_img, img_bytes)
                else:
                    sim = 0.0

                if self._is_stable_boundary(motion, sim):
                    bottom_motion_hits += 1
                else:
                    bottom_motion_hits = 0

                if bottom_motion_hits >= CONFIG["bottom_motion_threshold_hits"]:
                    log(f"   已到达边界，截图完成（位移={motion:.4f}）")
                    break

                if duplicate:
                    repeat_count += 1
                    log(f"   重复截图 ({repeat_count}/{CONFIG['duplicate_threshold']}) 相似度={sim:.4f}")
                    if repeat_count >= CONFIG['duplicate_threshold']:
                        log("   已到达边界，截图完成")
                        break
                else:
                    repeat_count = 0
                    seen_hashes.append(current_hash)
                    if len(seen_hashes) > 20:
                        seen_hashes = seen_hashes[-20:]
                    saved_count += 1
                    current_index = next_index + saved_count - 1
                    filename = f"{chat_name}_{current_index:03d}.png"
                    filepath = chat_dir / filename
                    with open(filepath, "wb") as f:
                        f.write(img_bytes)
                    log(f"   📸 [{saved_count:3d}] {filename}")

                prev_img = img_bytes

                if CONFIG["max_screenshots"] > 0 and saved_count >= CONFIG["max_screenshots"]:
                    log("   已达到截图上限")
                    break

                if mode == "down":
                    self._current_swipe_up()
                else:
                    self._current_swipe_down()
                if not self._sleep_interruptible(CONFIG["swipe_interval"], stop_event=stop_event):
                    log("   已停止")
                    break

        except KeyboardInterrupt:
            log("\n\n   已停止")

        log(f"\n✅ 截图完成: {saved_count} 张 → {chat_dir}")
        return saved_count

    def record_session(
        self,
        session_name: str,
        stop_event=None,
        auto_swipe: bool = False,
        swipe_direction: str = "up",
        status_cb=None,
        overwrite_existing: bool = False,
    ) -> int:
        """录屏模式：调用 Android 原生 screenrecord，导出 mp4 视频"""

        def log(message: str):
            print(message)
            if status_cb:
                status_cb(message)

        session_dir, video_path = self.build_record_session_paths(session_name, overwrite=overwrite_existing)
        remote_path = f"/sdcard/Download/{video_path.name}"

        log(f"\n开始视频录屏: {session_name}")
        log("   录屏输出格式: MP4 视频")
        log("   手动模式：请在手机上自行滑动；自动模式：程序将按设定方向滑动")
        log("   点击停止按钮后将结束录屏并自动拉取到本地\n")

        process, remote_file = start_screen_record(remote_path=remote_path)
        auto_swipe_count = 0

        try:
            while True:
                if stop_event and stop_event.is_set():
                    log("   正在停止录屏并导出视频...")
                    break

                if process.poll() is not None:
                    log("   设备录屏进程已结束，准备导出视频")
                    break

                if auto_swipe:
                    if swipe_direction == "up":
                        self._current_swipe_up()
                    else:
                        self._current_swipe_down()
                    auto_swipe_count += 1
                    if not self._sleep_interruptible(CONFIG["swipe_interval"], stop_event=stop_event):
                        log("   正在停止录屏并导出视频...")
                        break
                else:
                    if not self._sleep_interruptible(0.3, stop_event=stop_event):
                        log("   正在停止录屏并导出视频...")
                        break

        except KeyboardInterrupt:
            log("\n用户中断录屏，正在导出视频...")

        saved_path = stop_screen_record(process, remote_file, video_path)
        if saved_path.exists() and saved_path.stat().st_size > 0:
            log(f"\n视频录屏完成: {saved_path}")
            return 1

        log("\n视频录屏失败：未成功导出 mp4 文件")
        return 0

    def manual_capture(self, filename: str = None) -> str:
        """手动截图"""
        filepath = self.build_manual_capture_path(filename)

        img_bytes = take_screenshot()
        if img_bytes:
            with open(filepath, "wb") as f:
                f.write(img_bytes)
            print(f"   手动截图已保存: {filepath}")
            return str(filepath)
        else:
            print("   截图失败")
            return ""

    def manual_record_session(self, session_name: str, direction: str = "up") -> int:
        """手动录屏/采集会话：用户自己控制滑动，程序只负责截图记录"""
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        next_index = self._find_next_index(session_dir, session_name, ".png")

        print("\n手动录屏模式")
        print("   你可以在手机上自行滑动，程序会按回车记录当前画面。")
        print("   输入 q 结束，输入 s 保存当前帧并继续。\n")

        count = 0
        while True:
            cmd = input("[Enter=记录, s=记录并继续, q=结束] > ").strip().lower()
            if cmd == "q":
                break
            img = take_screenshot()
            if not img:
                print("   截图失败")
                continue
            count += 1
            filepath = session_dir / f"{session_name}_{next_index + count - 1:03d}.png"
            with open(filepath, "wb") as f:
                f.write(img)
            print(f"   已保存: {filepath}")
            if cmd == "s":
                continue
        print(f"\n录屏会话完成: {count} 张 → {session_dir}")
        return count

    def build_longshot_session_paths(self, session_name: str, overwrite: bool = False) -> tuple[Path, Path, Path]:
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = session_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        stitched_path = session_dir / f"{session_name}_longshot.png"
        if overwrite:
            for old_png in session_dir.glob("*.png"):
                try:
                    old_png.unlink()
                except OSError:
                    pass
            for old_frame in frames_dir.glob("*.png"):
                try:
                    old_frame.unlink()
                except OSError:
                    pass
            return session_dir, frames_dir, stitched_path

        if not stitched_path.exists():
            return session_dir, frames_dir, stitched_path

        next_index = self._find_next_index(session_dir, f"{session_name}_longshot", ".png")
        stitched_path = session_dir / f"{session_name}_longshot_{next_index:03d}.png"
        return session_dir, frames_dir, stitched_path

    def build_important_session_paths(self, session_name: str, overwrite: bool = False) -> tuple[Path, Path]:
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        crops_dir = session_dir / "important"
        crops_dir.mkdir(parents=True, exist_ok=True)
        if overwrite:
            for old_png in crops_dir.glob("*.png"):
                try:
                    old_png.unlink()
                except OSError:
                    pass
        return session_dir, crops_dir

    def _open_image(self, img_bytes: bytes) -> Image.Image:
        return Image.open(BytesIO(img_bytes)).convert("RGB")

    def _ensure_ocr_backend(self):
        if self._ocr_backend is not None:
            return self._ocr_backend

        try:
            numpy_module = importlib.import_module("numpy")
            rapidocr_module = importlib.import_module("rapidocr_onnxruntime")
            self._ocr_backend = "rapidocr"
            self._ocr_engine = rapidocr_module.RapidOCR()
            self._ocr_numpy = numpy_module
            return self._ocr_backend
        except Exception:
            pass

        try:
            pytesseract_module = importlib.import_module("pytesseract")
            self._ocr_backend = "pytesseract"
            self._ocr_engine = pytesseract_module
            self._tesseract_output = pytesseract_module.Output
            return self._ocr_backend
        except Exception:
            pass

        raise RuntimeError("未安装可用 OCR 依赖，请先安装 rapidocr-onnxruntime 或 pytesseract")

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).strip(" -—_·•|:：")

    @staticmethod
    def _rect_from_box(box) -> tuple[int, int, int, int] | None:
        if not box:
            return None
        try:
            if isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(item, (list, tuple)) for item in box):
                xs = [int(point[0]) for point in box]
                ys = [int(point[1]) for point in box]
                return min(xs), min(ys), max(xs), max(ys)
            if isinstance(box, (list, tuple)) and len(box) == 4:
                left, top, right, bottom = map(int, box)
                return left, top, right, bottom
        except Exception:
            return None
        return None

    @staticmethod
    def _merge_boxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
        valid = [box for box in boxes if box is not None]
        if not valid:
            return None
        left = min(box[0] for box in valid)
        top = min(box[1] for box in valid)
        right = max(box[2] for box in valid)
        bottom = max(box[3] for box in valid)
        return left, top, right, bottom

    @staticmethod
    def _expand_box(box: tuple[int, int, int, int], padding_x: int, padding_y: int, width: int, height: int) -> tuple[int, int, int, int]:
        left, top, right, bottom = box
        return (
            max(0, left - padding_x),
            max(0, top - padding_y),
            min(width, right + padding_x),
            min(height, bottom + padding_y),
        )

    @staticmethod
    def _crop_signature(box: tuple[int, int, int, int], text: str, kind: str) -> str:
        left, top, right, bottom = box
        return f"{kind}|{ScreenCapture._normalize_text(text).lower()}|{left // 40}:{top // 40}:{right // 40}:{bottom // 40}"

    def _ocr_lines_from_image(self, image: Image.Image) -> list[OCRLine]:
        backend = self._ensure_ocr_backend()
        if backend == "rapidocr":
            if self._ocr_numpy is None:
                raise RuntimeError("RapidOCR 需要 numpy")
            raw_result = self._ocr_engine(self._ocr_numpy.array(image.convert("RGB")))
            items = raw_result[0] if isinstance(raw_result, tuple) and raw_result else raw_result
            lines: list[OCRLine] = []
            for item in items or []:
                if not item or len(item) < 2:
                    continue
                box = self._rect_from_box(item[0])
                if box is None:
                    continue
                text = self._normalize_text(str(item[1]))
                if not text:
                    continue
                score = float(item[2]) if len(item) >= 3 and item[2] is not None else 0.0
                lines.append(OCRLine(text=text, box=box, score=score))
            return self._merge_ocr_lines(lines)

        if backend == "pytesseract":
            data = self._ocr_engine.image_to_data(image, output_type=self._tesseract_output.DICT, lang="chi_sim+eng")
            grouped: dict[tuple[int, int, int], list[OCRLine]] = {}
            for index, raw_text in enumerate(data.get("text", [])):
                text = self._normalize_text(str(raw_text))
                if not text:
                    continue
                try:
                    confidence = float(data.get("conf", [0])[index])
                except Exception:
                    confidence = 0.0
                if confidence < 0:
                    continue
                left = int(data.get("left", [0])[index])
                top = int(data.get("top", [0])[index])
                width = int(data.get("width", [0])[index])
                height = int(data.get("height", [0])[index])
                key = (
                    int(data.get("block_num", [0])[index]),
                    int(data.get("par_num", [0])[index]),
                    int(data.get("line_num", [0])[index]),
                )
                grouped.setdefault(key, []).append(OCRLine(text=text, box=(left, top, left + width, top + height), score=confidence))

            lines: list[OCRLine] = []
            for items in grouped.values():
                items.sort(key=lambda item: (item.box[1], item.box[0]))
                merged_text = self._normalize_text(" ".join(item.text for item in items if item.text))
                merged_box = self._merge_boxes([item.box for item in items])
                if merged_text and merged_box is not None:
                    lines.append(OCRLine(text=merged_text, box=merged_box, score=max(item.score for item in items)))
            return self._merge_ocr_lines(lines)

        raise RuntimeError("未找到可用 OCR 后端")

    def _merge_ocr_lines(self, lines: list[OCRLine]) -> list[OCRLine]:
        if not lines:
            return []
        ordered = sorted(lines, key=lambda item: ((item.box[1] + item.box[3]) / 2, item.box[0]))
        merged: list[OCRLine] = []
        current = ordered[0]
        for line in ordered[1:]:
            current_center = (current.box[1] + current.box[3]) / 2
            line_center = (line.box[1] + line.box[3]) / 2
            current_height = max(1, current.box[3] - current.box[1])
            if line_center - current_center <= max(18, int(current_height * 0.9)):
                current = OCRLine(
                    text=self._normalize_text(f"{current.text} {line.text}"),
                    box=self._merge_boxes([current.box, line.box]) or current.box,
                    score=max(current.score, line.score),
                )
            else:
                merged.append(current)
                current = line
        merged.append(current)
        return merged

    def _classify_important_text(self, text: str) -> str | None:
        cleaned = self._normalize_text(text)
        if not cleaned:
            return None
        lowered = cleaned.lower()
        for kind, pattern in IMPORTANT_PATTERNS:
            if pattern.search(cleaned):
                return kind
        if any(keyword.lower() in lowered for keyword in IMPORTANT_KEYWORDS):
            return "keyword"
        return None

    def scan_session_for_apk_and_links(self, session_name: str) -> dict:
        """扫描指定会话目录下的所有截图，识别 APK 安装包文件名和网址链接。"""
        chat_dir = self.output_dir / session_name
        result: dict = {
            "apk": [],
            "link": [],
            "apk_details": [],
            "link_details": [],
        }
        if not chat_dir.exists():
            return result

        try:
            self._ensure_ocr_backend()
        except Exception:
            return result

        apk_pattern: re.Pattern[str] | None = None
        link_pattern: re.Pattern[str] | None = None
        for kind, pattern in IMPORTANT_PATTERNS:
            if kind == "apk":
                apk_pattern = pattern
            elif kind == "link":
                link_pattern = pattern

        seen_apk: set[str] = set()
        seen_link: set[str] = set()

        for png_path in sorted(chat_dir.glob("*.png")):
            try:
                with Image.open(png_path) as img:
                    img_width, img_height = img.size
                    lines = self._ocr_lines_from_image(img)
            except Exception:
                continue

            for line in lines:
                text = line.text
                # 获取该行的 bounding box
                line_box = line.box  # (left, top, right, bottom)
                if apk_pattern:
                    for match in apk_pattern.finditer(text):
                        val = match.group(0).strip()
                        if val and val not in seen_apk:
                            seen_apk.add(val)
                            result["apk"].append(val)
                            result["apk_details"].append({
                                "value": val,
                                "file": png_path.name,
                                "box": line_box,  # 添加位置信息
                                "img_width": img_width,
                                "img_height": img_height,
                            })
                if link_pattern:
                    for match in link_pattern.finditer(text):
                        val = match.group(0).strip()
                        # 去掉尾部可能误抓的标点
                        val = val.rstrip('.,;:!?)]}>\\"')
                        if val and val not in seen_link:
                            seen_link.add(val)
                            result["link"].append(val)
                            result["link_details"].append({
                                "value": val,
                                "file": png_path.name,
                                "box": line_box,  # 添加位置信息
                                "img_width": img_width,
                                "img_height": img_height,
                            })

        return result

    def _important_crop_windows(self, lines: list[OCRLine], frame_width: int, frame_height: int, before: int = 2, after: int = 2) -> list[tuple[str, str, tuple[int, int, int, int]]]:
        if not lines:
            return []

        windows: list[tuple[str, str, tuple[int, int, int, int]]] = []
        for index, line in enumerate(lines):
            kind = self._classify_important_text(line.text)
            if not kind:
                continue
            start = max(0, index - before)
            end = min(len(lines), index + after + 1)
            related = lines[start:end]
            merged_box = self._merge_boxes([item.box for item in related])
            if merged_box is None:
                continue
            margin_x = max(18, int(frame_width * 0.03))
            margin_y = max(20, int(frame_height * 0.02))
            expanded = self._expand_box(merged_box, margin_x, margin_y, frame_width, frame_height)
            windows.append((kind, line.text, expanded))

        if not windows:
            return []

        windows.sort(key=lambda item: (item[2][1], item[2][0]))
        merged_windows: list[tuple[str, str, tuple[int, int, int, int]]] = []
        current_kind, current_text, current_box = windows[0]
        for kind, text, box in windows[1:]:
            gap = box[1] - current_box[3]
            if gap <= max(24, int(frame_height * 0.03)):
                current_box = self._merge_boxes([current_box, box]) or current_box
                current_text = self._normalize_text(f"{current_text} | {text}")
                current_kind = current_kind if current_kind == kind else f"{current_kind}+{kind}"
            else:
                merged_windows.append((current_kind, current_text, current_box))
                current_kind, current_text, current_box = kind, text, box
        merged_windows.append((current_kind, current_text, current_box))
        return merged_windows

    def important_capture_and_crop(
        self,
        session_name: str,
        stop_event=None,
        status_cb=None,
        overwrite_existing: bool = False,
        skip_initial_seek: bool = False,
    ) -> tuple[int, str]:
        """重点内容模式：识别 APK / 链接 / 账号等内容，并只保存上下文裁剪图。"""

        def log(message: str):
            print(message)
            if status_cb:
                status_cb(message)

        session_dir, crops_dir = self.build_important_session_paths(session_name, overwrite=overwrite_existing)
        try:
            self._ensure_ocr_backend()
        except Exception as exc:
            raise RuntimeError(f"重点内容模式不可用：{exc}") from exc

        if not skip_initial_seek:
            self.scroll_to_top(stop_event=stop_event)
            if stop_event and stop_event.is_set():
                log("   ⏹已停止重点内容模式")
                return 0, ""
        else:
            log("\n⏭重点内容模式将从当前位置开始")

        log(f"\n开始重点内容截图: {session_name}")
        log(f"   输出目录: {crops_dir}")
        log("   当前策略：识别 APK / 链接 / 账号等内容，并裁取上下文")

        saved_count = 0
        seen_crop_signatures: set[str] = set()
        seen_frame_hashes: list[str] = []
        prev_img: bytes | None = None
        repeat_count = 0
        bottom_motion_hits = 0

        while True:
            if stop_event and stop_event.is_set():
                log("   已停止重点内容模式")
                break

            img_bytes = take_screenshot()
            if not img_bytes:
                log("   截图失败，准备重试...")
                if not self._sleep_interruptible(0.4, stop_event=stop_event):
                    break
                continue

            current_hash = screenshot_hash(img_bytes)
            duplicate = current_hash in seen_frame_hashes
            sim = 0.0
            motion = 1.0
            if prev_img is not None:
                sim = image_similarity(prev_img, img_bytes)
                duplicate = duplicate or sim >= CONFIG["similarity_threshold"]
                motion = estimate_vertical_shift(prev_img, img_bytes)

            if self._is_stable_boundary(motion, sim):
                bottom_motion_hits += 1
            else:
                bottom_motion_hits = 0

            if bottom_motion_hits >= CONFIG["bottom_motion_threshold_hits"]:
                log(f"   已到达边界，重点内容截图完成（位移={motion:.4f}）")
                break

            frame = self._open_image(img_bytes)
            try:
                lines = self._ocr_lines_from_image(frame)
            except Exception as exc:
                log(f"   OCR 失败：{exc}")
                lines = []

            windows = self._important_crop_windows(lines, frame.width, frame.height)
            saved_this_frame = 0
            for kind, text, box in windows:
                signature = self._crop_signature(box, text, kind)
                if signature in seen_crop_signatures:
                    continue
                seen_crop_signatures.add(signature)
                crop = frame.crop(box)
                saved_count += 1
                saved_this_frame += 1
                crop_path = crops_dir / f"{session_name}_important_{saved_count:03d}.png"
                crop.save(crop_path, format="PNG")
                log(f"   [{saved_count:3d}] {crop_path.name} · {kind} · {self._normalize_text(text)[:60]}")

            if duplicate and saved_this_frame == 0:
                repeat_count += 1
                log(f"   重复截图 ({repeat_count}/{CONFIG['duplicate_threshold']}) 相似度={sim:.4f}")
                if repeat_count >= CONFIG["duplicate_threshold"]:
                    log("   已到达边界，重点内容截图完成")
                    break
            else:
                repeat_count = 0
                seen_frame_hashes.append(current_hash)
                if len(seen_frame_hashes) > 20:
                    seen_frame_hashes = seen_frame_hashes[-20:]

            prev_img = img_bytes

            if CONFIG["max_screenshots"] > 0 and saved_count >= CONFIG["max_screenshots"]:
                log("   已达到截图上限")
                break

            self._current_swipe_up()
            if not self._sleep_interruptible(CONFIG["swipe_interval"], stop_event=stop_event):
                break

        if saved_count == 0:
            log("\n重点内容模式失败：没有识别到可保存的重点内容")
            return 0, ""

        manifest_path = session_dir / f"{session_name}_important_manifest.txt"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(f"session={session_name}\n")
                f.write(f"count={saved_count}\n")
                f.write(f"output_dir={crops_dir}\n")
        except OSError:
            pass

        log(f"\n重点内容截图完成: {saved_count} 张 → {crops_dir}")
        return saved_count, str(crops_dir)

    def _estimate_vertical_overlap(self, upper: Image.Image, lower: Image.Image) -> int:
        from PIL import ImageChops, ImageStat

        upper_gray = upper.convert("L")
        lower_gray = lower.convert("L")
        width, height = upper_gray.size
        min_overlap = max(80, int(height * 0.12))
        max_overlap = max(min_overlap, int(height * 0.45))
        step = max(8, int(height * 0.02))

        best_overlap = 0
        best_score = float('inf')
        for overlap in range(min_overlap, max_overlap + 1, step):
            upper_part = upper_gray.crop((0, height - overlap, width, height)).resize((64, max(16, int(overlap * 64 / max(width, 1)))), Image.Resampling.BILINEAR)
            lower_part = lower_gray.crop((0, 0, width, overlap)).resize(upper_part.size, Image.Resampling.BILINEAR)
            diff = ImageChops.difference(upper_part, lower_part)
            score = sum(ImageStat.Stat(diff).mean) / len(ImageStat.Stat(diff).mean)
            if score < best_score:
                best_score = score
                best_overlap = overlap

        if best_score > 18:
            return 0
        return best_overlap

    def _stitch_images_vertically(self, images: list[Image.Image]) -> Image.Image:
        if not images:
            raise ValueError("没有可拼接的图片")
        if len(images) == 1:
            return images[0]

        stitched = images[0]
        for current in images[1:]:
            overlap = self._estimate_vertical_overlap(stitched, current)
            if overlap <= 0:
                overlap = 0
            new_height = stitched.height + max(1, current.height - overlap)
            canvas = Image.new("RGB", (max(stitched.width, current.width), new_height), (255, 255, 255))
            canvas.paste(stitched, (0, 0))
            crop_box = (0, overlap, current.width, current.height)
            canvas.paste(current.crop(crop_box), (0, stitched.height))
            stitched = canvas
        return stitched

    def _try_system_longshot_enhanced(self, session_name: str, session_dir: Path, stitched_path: Path, stop_event=None, status_cb=None) -> tuple[int, str]:
        def log(message: str):
            print(message)
            if status_cb:
                status_cb(message)

        if stop_event and stop_event.is_set():
            return 0, ''

        created_after = time.time() - 2
        log('   尝试系统长截图增强模式：先触发系统截图，再查找“长截图/滚动截图/捕获更多”等入口')
        trigger_system_screenshot()
        if not self._sleep_interruptible(1.2, stop_event=stop_event):
            return 0, ''

        tapped = try_tap_ui_keywords(system_longshot_keywords())
        if not tapped:
            raise RuntimeError('未找到系统长截图按钮')
        log(f"   已点击系统长截图候选：{tapped.get('text') or tapped.get('desc') or tapped.get('keyword')}")

        for attempt in range(1, 9):
            if stop_event and stop_event.is_set():
                return 0, ''
            try:
                saved_path = try_fetch_latest_system_screenshot(stitched_path, created_after=created_after)
                if saved_path.exists() and saved_path.stat().st_size > 0:
                    log(f'   已获取系统长截图产物：{saved_path.name}')
                    return 1, str(saved_path)
            except Exception as exc:
                if attempt == 1:
                    log(f'   等待系统长截图生成中：{exc}')
            extra_tapped = try_tap_ui_keywords([
                '继续滚动', '继续截取', '继续截图', '下一屏', '下一页', 'more', 'capture more', 'scroll', '滚动',
            ])
            if extra_tapped:
                log(f"   检测到继续截取入口，已点击：{extra_tapped.get('text') or extra_tapped.get('desc') or extra_tapped.get('keyword')}")
            if not self._sleep_interruptible(1.0, stop_event=stop_event):
                return 0, ''

        raise RuntimeError('系统长截图未生成可拉取文件')

    def longshot_capture_and_stitch(
        self,
        session_name: str,
        mode: int = 1,
        stop_event=None,
        status_cb=None,
        overwrite_existing: bool = False,
    ) -> tuple[int, str]:
        """长截图：自动滚动抓多张并拼接成一张 PNG。

        mode:
            1 - 系统长截图增强优先，失败自动回退到拼接模式
            2 - 从当前位置开始拼接（偏手动入口，自定义命名）
            3 - 从当前位置开始自动向下拼接，不判断顶端
        """

        def log(message: str):
            print(message)
            if status_cb:
                status_cb(message)

        session_dir, frames_dir, stitched_path = self.build_longshot_session_paths(session_name, overwrite=overwrite_existing)

        if mode == 1:
            try:
                system_count, system_path = self._try_system_longshot_enhanced(
                    session_name,
                    session_dir,
                    stitched_path,
                    stop_event=stop_event,
                    status_cb=status_cb,
                )
                if system_count > 0 and system_path:
                    return system_count, system_path
                if stop_event and stop_event.is_set():
                    log('   已停止长截图任务')
                    return 0, ''
            except Exception as exc:
                log(f'   系统长截图增强模式失败，自动回退拼接模式：{exc}')

            self.scroll_to_top(stop_event=stop_event)
            if stop_event and stop_event.is_set():
                log('   已停止长截图任务')
                return 0, ''
        elif mode in (2, 3):
            log('\n长截图将从当前位置开始')

        captured_bytes: list[bytes] = []
        seen_hashes: list[str] = []
        prev_img: bytes | None = None
        repeat_count = 0
        bottom_motion_hits = 0

        log(f'\n开始长截图: {session_name}')
        log(f'   输出目录: {session_dir}')
        if mode == 1:
            log('   当前策略：系统长截图增强失败后，已回退为自动拼接长截图')

        while True:
            if stop_event and stop_event.is_set():
                log('    已停止长截图任务')
                break

            img_bytes = take_screenshot()
            if not img_bytes:
                log('    截图失败，准备重试...')
                if not self._sleep_interruptible(0.4, stop_event=stop_event):
                    break
                continue

            current_hash = screenshot_hash(img_bytes)
            duplicate = current_hash in seen_hashes
            sim = 0.0
            motion = 1.0
            if prev_img is not None:
                sim = image_similarity(prev_img, img_bytes)
                duplicate = duplicate or sim >= CONFIG['similarity_threshold']
                motion = estimate_vertical_shift(prev_img, img_bytes)

            if self._is_stable_boundary(motion, sim):
                bottom_motion_hits += 1
            else:
                bottom_motion_hits = 0

            if bottom_motion_hits >= CONFIG["bottom_motion_threshold_hits"]:
                log(f'   已到达边界，停止抓取并开始拼接（位移={motion:.4f}）')
                break

            if duplicate:
                repeat_count += 1
                log(f'   检测到重复页面 ({repeat_count}/{CONFIG["duplicate_threshold"]}) 相似度={sim:.4f}')
                if repeat_count >= CONFIG['duplicate_threshold']:
                    log('   已到达边界，停止抓取并开始拼接')
                    break
            else:
                repeat_count = 0
                seen_hashes.append(current_hash)
                if len(seen_hashes) > 20:
                    seen_hashes = seen_hashes[-20:]
                captured_bytes.append(img_bytes)
                frame_path = frames_dir / f'{session_name}_{len(captured_bytes):03d}.png'
                with open(frame_path, 'wb') as f:
                    f.write(img_bytes)
                log(f'   已抓取第 {len(captured_bytes)} 张: {frame_path.name}')

            prev_img = img_bytes

            if CONFIG['max_screenshots'] > 0 and len(captured_bytes) >= CONFIG['max_screenshots']:
                log('   已达到截图上限，开始拼接')
                break

            self._current_swipe_up()
            if not self._sleep_interruptible(CONFIG['swipe_interval'], stop_event=stop_event):
                break

        if not captured_bytes:
            log('\n长截图失败：没有抓取到任何有效图片')
            return 0, ''

        max_images_per_output = 20
        output_paths: list[Path] = []

        for chunk_index, start in enumerate(range(0, len(captured_bytes), max_images_per_output), start=1):
            chunk = captured_bytes[start:start + max_images_per_output]
            images = [self._open_image(item) for item in chunk]
            stitched = self._stitch_images_vertically(images)
            if len(captured_bytes) <= max_images_per_output:
                output_path = stitched_path
            else:
                output_path = session_dir / f'{stitched_path.stem}_part{chunk_index:02d}{stitched_path.suffix}'
            stitched.save(output_path, format='PNG')
            output_paths.append(output_path)
            log(f'   已输出第 {chunk_index} 组长图（{len(chunk)} 张拼接）: {output_path.name}')

        if len(output_paths) == 1:
            log(f'\n长截图完成: {len(captured_bytes)} 张 → {output_paths[0]}')
        else:
            log(f'\n长截图完成: {len(captured_bytes)} 张，按每组最多 {max_images_per_output} 张分段输出，共 {len(output_paths)} 张长图，目录：{session_dir}')
        return len(captured_bytes), str(output_paths[0])

