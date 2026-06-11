# ChatScreenshot

在[0xSec623/ChatExtractor-Screenshot: 基于 Python + ADB 的轻量级聊天截图采集工具，支持自动滚动、智能去重与结构化存储，全程离线、无需 AI。](https://github.com/0xSec623/ChatExtractor-Screenshot)基础上进行修改的

感谢[0xSec623](https://github.com/0xSec623)

> 当前主线：**Qt GUI（优先 PySide6，失败自动回退 PyQt5）+ CLI 回退保留**

---

## 1. 项目简介

ChatExtractor-Screenshot 用于在 **Android 设备已开启 ADB 调试** 的前提下，完成以下本地工作流：

- 聊天截图采集
- 原生录屏导出（MP4）
- 长截图自动拼接
- 已安装 App 列表浏览 / 分页 / 筛选 / APK 导出 / 单项卸载
- 运行日志查看与导出

整个流程默认在本机执行，输出落在项目 `projects/` 目录下，适合：

- 聊天记录留存
- 安全测试过程取证
- App 资产导出与归档
- 本地辅助分析

---

## 2. 当前能力一览

### 核心特性

- ✅ **纯本地运行**：不上传云端
- ✅ **GUI + CLI 双模式**：GUI 不可用时自动回退 CLI
- ✅ **Qt GUI 主线**：优先 `PySide6`，失败回退 `PyQt5`
- ✅ **截图 / 录屏 / 长截图 / App 导出 / 日志** 分页拆分
- ✅ **录屏导出真实 MP4**，不是截图序列伪视频
- ✅ **长截图支持自动滚动拼接**，默认每 20 张分段输出
- ✅ **App 导出页支持分页 / 搜索 / 页大小切换 / 当前页/筛选批量勾选 / 单项卸载**
- ✅ **主题切换**：奶油主题 / 亮白主题 / 暗黑主题
- ✅ **记忆上次主题**：下次启动保留用户上次选择
- ✅ **运行日志中心**：支持实时查看、磁盘重载、导出副本
- ✅ **0xSec 品牌展示**

### 模块说明

| 模块     | 说明                                         |
| -------- | -------------------------------------------- |
| 截图模式 | 自动聊天截图、手动命名、结构化保存           |
| 录屏模式 | 原生 `screenrecord` 录制并导出 MP4         |
| 长截图   | 自动抓取多张截图并拼接成长图，默认 20 张一组 |
| App 导出 | 浏览已安装应用、筛选、分页、导出 APK、卸载   |
| 运行日志 | 查看任务状态、ADB 过程、导出与异常           |

---

## 3. 最近一次重点优化：App 导出刷新提速 / 防卡死

用户反馈：**App 导出中的“刷新列表”速度过慢，并且会导致电脑卡死。**

本次已完成第一轮实质优化，核心是把“全量重型解析”改成“快速列表 + 受控补名 + 缓存复用”。

### 根因

旧思路里，App 列表刷新阶段容易对大量包名逐个做重型名称解析，典型代价包括：

- 逐包执行额外 ADB 查询
- 逐包走 `dumpsys package` / APK 路径 / 标签解析
- 数量一多时，ADB 往返和解析成本会迅速放大
- 最终表现为：刷新慢、CPU 飙升、界面假死、整机发卡

### 已落地的优化

在 `adb_utils.py` 中，App 列表刷新已改为：

1. **先用一次快速命令取包列表**优先使用：

   - `adb shell cmd package list packages -i -U`
   - 失败时回退 `adb shell pm list packages`
2. **名称解析不再全量硬解**首次刷新时：

   - 先直接显示包列表
   - 未命中的名称先给轻量占位：`未识别（包名）`
   - 再仅对有限数量的包做名称补齐
3. **加入内存缓存**已解析过的包名会缓存到内存中，同一轮会话后续刷新直接复用。
4. **控制首次补名上限，避免 ADB 风暴**当前策略：

   - 包含系统应用时：最多补 24 个名称
   - 仅第三方应用时：最多补 40 个名称
5. **GUI 刷新仍走后台线程**
   避免在主线程直接阻塞界面。

### 当前效果

- App 列表首屏刷新明显更快
- 不再因为全量重解析导致电脑明显卡死
- 再次刷新时，缓存命中后速度进一步提升
- UI 仍保留分页、筛选、导出、卸载链路

### 两次迭代之间的提升点

#### 第一阶段：先把“能用”做出来

- 能拉起 App 列表
- 能显示名称 / 包名 / 安装来源
- 能做导出与卸载

#### 第二阶段：针对性能瓶颈做收口

- 不再对所有包逐个做重型名称解析
- 加入**快速包列表**策略
- 加入**受控补名上限**策略
- 加入**会话级名称缓存**
- 明显降低刷新时的整机卡顿感

### 还可以继续做的下一步（可选）

如果你还要继续把体验再抬一档，后续建议是：

- **分批懒加载名称**：先显示包名列表，再逐批补齐名称
- **缓存落盘**：把名称缓存写入本地 JSON，下次启动继续复用

这两项还没在本轮里落地，但非常适合作为下一轮增强。

---

## 4. 运行环境

### 必需依赖

- Android 手机，已开启 USB 调试
- 项目内置 ADB 位于 `tools/adb/adb.exe`
- Python **3.10+**

### Python 依赖

见 `requirements.txt`：

- `Pillow>=10.0.0`
- `PySide6>=6.5.0`
- `PyQt5>=5.15.0`

> GUI 优先尝试 `PySide6`，若导入失败则自动尝试 `PyQt5`。

---

## 5. 安装与启动

### Linux

```bash
cd ChatExtractor-Screenshot
python3 -m pip install -r requirements.txt
adb devices
```

### Windows

#### 方案 A：内置 ADB（推荐给没有技术基础的用户）

**你只需操作一次（打包者）：**

1. **准备打包**（确保你的电脑已安装 ADB）：

   ```bat
   # 双击运行打包脚本
   tools/prepare_release.bat

   # 或者命令行
   python tools/prepare_release.py
   ```
2. **按提示操作**：脚本会自动找到你系统的 ADB 并复制到项目中
3. **分享**：将整个项目文件夹压缩发给用户

**用户拿到后只需：**

1. 解压文件夹
2. 双击 `start.bat`
3. 连接手机开始使用

> **无需联网下载、无需手动安装 ADB、双击即用**

---

#### 方案 B：自动下载 ADB（保持项目轻量）

如果希望保持项目体积小，可以让用户首次使用时自动下载：

```bat
start.bat
```

首次运行会自动检测并提示下载 ADB（需要联网，约 15MB）。

### 启动方式

#### Windows 启动

直接双击 `start.bat`。

#### 默认启动（开发环境）

```bash
python3 main.py
```

逻辑：

- 有 Qt 且当前环境存在图形显示：启动 GUI
- 否则：自动回退 CLI

#### 强制 GUI

```bash
python3 main.py --gui
```

#### 强制 CLI

```bash
python3 main.py --cli
```

#### 启动脚本

```bash
start.bat
```

---

## 6. GUI 使用说明

GUI 顶部提供主题切换与全局状态提示，主界面分为 5 个标签页：

1. **截图模式**
2. **录屏模式**
3. **长截图**
4. **App 导出**
5. **运行日志**

### 6.1 截图模式

适合聊天记录逐屏采集。

特点：

- 自动检测设备和当前 App
- 自动创建项目目录
- 支持模式切换与自定义命名
- 日志独立记录

### 6.2 录屏模式

使用 Android 原生 `screenrecord`：

- 导出结果为 **MP4**
- 停止时会等待远端文件稳定后再拉取
- 内部带有轻量完整性校验，减少半成品 MP4 误判成功

### 6.3 长截图

特点：

- 自动抓取多张截图
- 自动纵向拼接
- 默认 **每 20 张分段输出**
- 抓取不到有效图片时会直接报错结束

### 6.4 App 导出

当前支持：

- 刷新已安装 App 列表
- 搜索名称 / 包名 / 安装来源
- 每页显示 10 / 20 / 30
- 上一页 / 下一页
- 全选本页 / 取消本页 / 反选本页
- 全选筛选结果 / 清空全部勾选
- 导出勾选 APK
- 导出当前页 APK
- 打开导出目录
- 单项卸载 App

### 6.5 运行日志

支持：

- 实时日志显示
- 自动滚动到底部
- 刷新视图
- 从磁盘重载
- 打开日志目录
- 导出日志副本
- 清空界面日志

---

## 7. CLI 模式

当 GUI 不可用时，可以继续走命令行回退：

```bash
python3 main.py --cli
```

CLI 目前保留以下主入口：

- 截图模式
- 录屏模式
- 长截图模式

这保证了 Qt 环境异常时，主流程仍然可跑。

---

## 8. 输出目录结构

默认输出根目录：

```text
./projects
```

典型结构如下：

```text
projects/
└── 设备名/
    └── App名_包名/
        ├── capture/
        │   ├── 会话名/
        │   └── logs/
        ├── record/
        │   ├── 会话名.mp4
        │   └── logs/
        ├── longshot/
        │   ├── 会话名/
        │   ├── 会话名.png
        │   ├── 会话名_part02.png
        │   └── logs/
        └── app_export/
            ├── apks/
            └── logs/
```

---

## 9. 配置说明

`config.py` 当前核心配置：

```python
CONFIG = {
    "swipe_duration": 450,
    "swipe_interval": 0.9,
    "top_swipe_duration": 260,
    "top_swipe_rounds": 4,
    "top_stable_threshold": 2,
    "max_screenshots": 0,
    "duplicate_threshold": 4,
    "similarity_threshold": 0.985,
    "top_detection_threshold": 0.990,
    "screenshot_format": "png",
    "crop_status_bar": True,
    "crop_bottom_bar": True,
    "output_root": "./projects",
}
```

说明：

- `max_screenshots = 0` 表示不设上限，直到手动停止或触发重复边界
- `duplicate_threshold` 越高，越不容易过早停止
- `swipe_interval` 可用于平衡速度与稳定性

---

## 10. 常见问题

### Q1：GUI 启动失败怎么办？

先直接看真实报错：

```bash
python3 main.py --gui
```

排查顺序：

- 是否安装了 `PySide6` 或 `PyQt5`
- 当前是否存在图形显示环境
- Python 是否为 3.10+
- `adb` 是否可直接执行

### Q2：没有桌面环境还能用吗？

可以，直接用 CLI：

```bash
python3 main.py --cli
```

### Q3：App 导出刷新还是慢怎么办？

当前已做第一轮性能优化；如果设备 App 特别多，仍建议：

- 先取消“包含系统应用”
- 先用搜索定位目标 App
- 后续可继续加“分批懒加载名称 + 缓存落盘”

### Q4：录屏为什么不是即时停止后马上导出？

因为需要等待手机侧 MP4 文件 flush 稳定，否则容易拉回半成品文件。

### Q5：长截图为什么会分成多张长图？

当前默认每 20 张截图分段拼接，避免单张图过大导致保存慢、内存涨得过高。

---

## 11. 当前项目文件

当前核心文件：

```text
main.py
adb_utils.py
capture.py
config.py
README.md
GUIDE.md
requirements.txt
start.bat
projects/
```

本轮已顺手清理不应保留的开发临时产物：

- `__pycache__/`
- `decompiled_out/`
- `main.decompiled.py`
- `main.py.bak_qt_migration`

---

## 12. 后续建议

优先级建议如下：

1. **App 名称分批懒加载**
2. **App 名称缓存落盘**
3. 导出页增加“刷新中进度提示 / 已补名数量”
4. 更细的导出失败原因展示
5. 长截图参数可视化配置

---

## 13. 免责声明

本工具仅应用于**合法授权**场景。请勿将其用于未授权数据采集、侵犯隐私或违法用途。

---

## 14. 一句话总结

> ChatExtractor-Screenshot 现在已经是一套 **Qt GUI 主线 + CLI 回退** 的本地 Android 辅助取证工具，支持截图、MP4 录屏、长截图、App 导出和日志查看，并且刚完成了一轮 **App 列表刷新防卡死优化**。

---

## 15. Windows ADB 使用说明

### 两种方案对比

| 方案                         | 适用场景                  | 特点                                   |
| ---------------------------- | ------------------------- | -------------------------------------- |
| **内置 ADB（方案 A）** | 分享给没有技术基础的用户  | ADB 已包含在项目内，双击即用，无需联网 |
| **自动下载（方案 B）** | 你自己使用或通过 Git 分享 | 项目体积小，首次运行自动下载           |

### 方案 A：内置 ADB（推荐给普通用户）

打包者（你）操作一次：

```bat
# 双击运行
tools/prepare_release.bat
```

然后分享整个项目文件夹即可。

### 方案 B：自动下载 ADB

用户首次运行时按提示下载（需要联网）：

```bat
start.bat
```

### ADB 许可证声明

本项目使用的 ADB 来自 [Android SDK Platform Tools](https://developer.android.com/studio/releases/platform-tools)，由 Google LLC 开发，遵循 **Apache License 2.0**。

- 官方来源：https://developer.android.com/studio/releases/platform-tools
- 许可证文本：见 `tools/ADB_LICENSE.txt`
- Apache 2.0 全文：https://www.apache.org/licenses/LICENSE-2.0

**分发说明**：分享包含 ADB 的项目时，请确保同时包含 `tools/ADB_LICENSE.txt` 文件。

打包命令：python.exe -m PyInstaller --clean --noconfirm ChatExtractor.spec
