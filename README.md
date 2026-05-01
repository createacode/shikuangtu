# 实况照片播放器（目前只适配了oppo，其他手机实况图尚未适配）
适配oppo手机拍摄的实况照片的照片播放器，可查看照片和里面的视频

##【最新请查看重构版】实况照片播放器 https://github.com/createacode/LivePhotoPlayer

![实况图播放器UI界面](https://github.com/createacode/shikuangtu/blob/main/shikuangtu_UI.png?raw=true)

## 实况照片播放器 - 开发文档

## 1. 项目概述

**实况照片播放器** 是一款桌面端图像与视频浏览工具，专门用于查看 OPPO、华为等厂商的“实况照片”——即内嵌短视频的 JPEG/HEIC 文件。程序能够自动提取照片中的视频流，并利用 VLC 媒体引擎进行播放，同时提供常规图片浏览、缩放拖拽、键盘导航、文件列表、导出照片/视频等完整功能。应用程序使用 PyQt5 构建 GUI，通过 VLC 的 libvlc 库实现视频解码与渲染，并借助 ExifTool 解析图片元数据及提取内嵌视频。

## 2. 技术栈

| 组件            | 技术选型/版本                | 作用                                                                 |
| --------------- | --------------------------- | -------------------------------------------------------------------- |
| 编程语言        | Python 3.8 – 3.13           | 主开发语言，平衡开发效率与跨平台能力                                  |
| GUI 框架        | PyQt5 (≥5.15)               | 提供窗口、控件、布局、事件处理及 Qt 风格的跨平台界面                  |
| 视频播放引擎    | libvlc (python-vlc 3.0+)    | 基于 VLC 的多格式媒体播放、渲染到 Qt 控件、调速/音量/状态控制         |
| 图像处理        | Pillow (≥9.0) + pillow-heif | 常规图片（JPEG/PNG/TIFF）及 HEIC 格式的读取与 EXIF 提取               |
| 元数据提取      | ExifTool (12.x)             | 读取照片的拍摄日期、实况视频流提取（通过子进程调用）                  |
| 日志系统        | Python logging + RotatingHandler | 输出运行日志，便于调试与异常追踪                                      |
| 打包工具        | PyInstaller (≥5.0)          | 将程序及其依赖（VLC 库、ExifTool、资源文件）打包为单文件 Windows EXE  |
| 进程通信        | subprocess                  | 安全调用 exiftool.exe 获取元数据和视频数据                            |
| 并发与线程      | QThread + QMutex             | 视频提取、照片导出等耗时任务在后台线程执行，避免 UI 阻塞               |

## 3. 系统架构

整体采用 **MVC 模式**，其中：
- **模型（Model）**：图像/视频的数据模型，包括文件路径、元信息、临时视频路径、当前索引等。
- **视图（View）**：Qt 控件构成的界面，包括主窗口、堆叠窗口（图片滚动区和视频容器）、工具栏、文件列表停靠窗口、状态栏控制栏等。
- **控制器（Controller）**：UI 事件（点击、拖拽、快捷键）触发的业务逻辑，以及 VLC 播放状态的回调处理。

### 3.1 模块划分

| 模块名               | 职责                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `main.py`            | 应用程序入口，设置 AppUserModelID（Windows 任务栏图标），解析命令行参数 |
| `LivePhotoViewer`    | 主窗口类：包含 UI 构建、事件过滤、缩放拖动、播放控制、文件列表管理等   |
| `VideoExtractor`     | QThread 子类：后台调用 exiftool 提取照片内嵌视频，生成临时 MP4 文件    |
| `PhotoExportThread`  | QThread 子类：后台导出照片（HEIC 转 JPEG 或直接复制）                 |
| 辅助函数模块         | 日志配置、资源路径解析、exiftool 查找、HEIC 支持检测、日期读取等      |

### 3.2 数据流

1. **打开照片** → 主线程加载图片 → 显示在 `QScrollArea` 中 → 启动 `VideoExtractor` 线程提取视频 → 提取成功后回调主线程保存临时视频路径。
2. **播放实况** → 主线程使用 `vlc.Instance` 创建媒体实例 → 将视频渲染到 `QWidget`（通过 `winId()` 设置窗口句柄）→ 播放。
3. **切换照片** → 停止当前播放（等待 VLC 状态 Stopped）→ 释放临时视频资源 → 加载新图片 → 重新启动视频提取线程。

### 3.3 关键依赖关系

```
main.py → LivePhotoViewer → vlc.Instance → libvlc.dll (本地 VLC 目录)
                     → VideoExtractor → exiftool.exe (本地或 PATH)
                     → load_image_pixmap → Pillow / pillow-heif
```

## 4. 核心功能实现说明

### 4.1 实况视频提取

- **原理**：OPPO 等厂商的实况照片将短视频数据存放在 JPEG 的 `MotionPhotoVideo`、`VideoFile` 或 `EmbeddedVideo` **Exif** 标签中。ExifTool 可以提取这些标签的二进制数据并输出为 MP4 文件。
- **流程**：
  1. 用户打开照片后，主线程通过 `find_exiftool()` 定位 `exiftool.exe` 路径。
  2. 创建 `VideoExtractor` 后台线程，依次尝试三个标签名，调用 `exiftool -b -TagName picture.jpg`。
  3. 若输出数据以 `ftyp` 开头（MP4 文件头），则将其写入临时文件（`tempfile.mkstemp`）。
  4. 临时文件路径回调主线程，更新 `self.current_temp_video` 并显示“实况视频就绪”。
- **容错**：若所有标签均无有效数据，则回调 `error` 信号，显示“未找到内嵌视频”。

### 4.2 缩放与拖动

- **允许缩放条件**：只有当 `self.original_pixmap` 存在且 `current_image_path` 非空时。
- **缩放步长**：1.05 倍，使滚轮操作更加平滑（原 1.2 倍被用户要求降低）。
- **以鼠标为中心缩放**：在 `_apply_scale` 方法中，如果提供了 `anchor_pos`（鼠标在图片上的局部坐标），则根据原图片大小和缩放后新大小的比例，重新计算滚动条位置，使该点保持在视口中心附近。
- **拖动逻辑**：只有当当前缩放比例大于适应窗口比例时，左键按下进入拖动模式，记录滚动条起始值，移动时更新滚动条位置。

### 4.3 文件列表与文件夹导航

- **列表生成**：打开照片后，调用 `scan_folder_images` 扫描同一文件夹下所有支持格式的图片（`.jpg`、`.jpeg`、`.heic`、`.png` 等），按文件名排序后存储至 `self.current_folder_images`。
- **索引定位**：使用 `os.path.normpath` 规范化路径，避免因斜杠方向不一致（`/` vs `\`）导致的索引查找失败。
- **列表更新**：每次切换照片都会重新生成列表并高亮当前项，且保持原有滚动位置（通过 `scrollToItem` 恢复旧行）。
- **上一张/下一张**：基于 `current_index` ±1 进行切换，到达边界时显示柔性提示（状态栏临时消息）。

### 4.4 底部控制栏响应式隐藏

- **阈值**：`self.control_widget.width() < 800` 时隐藏“速度”标签、速度下拉框和“静音”按钮；宽度 ≥800 时显示。
- **实现**：在 `resizeEvent` 中检查宽度，并直接设置控件的 `hide()` 或 `show()`。因为布局中的 `addStretch()` 保证了中间按钮组居中，隐藏右侧控件不会导致布局错乱。

### 4.5 系统托盘与退出机制

- **托盘创建**：使用 `QSystemTrayIcon`，如果系统托盘可用则创建，图标为 `app.ico`。
- **关闭行为**：重写 `closeEvent`，如果托盘图标存在且 `self._closing` 为 False，则忽略关闭事件，隐藏主窗口并显示托盘提示；否则执行真正的退出流程（清理临时文件、停止播放）。
- **彻底退出**：可通过托盘菜单或主窗口“文件”菜单中的“退出”调用 `quit_app()`，设置 `_closing = True` 后关闭窗口。

### 4.6 VLC 播放防卡死

- **互斥锁**：所有播放相关操作（`toggle_play_pause`、`stop_control`、`_full_stop_and_reset`）均使用 `QMutexLocker(self._play_lock)` 保证线程安全。
- **状态切换标志**：`self._is_switching` 用于防止在图片切换过程中重复调用播放控制。
- **安全停止**：`_stop_vlc_safely` 中调用 `vlc_player.stop()` 后循环等待 `get_state() == vlc.State.Stopped`，最多 1 秒，确保 VLC 完全停止再设置 media 为 None，避免残留回调冲突。

## 5. 配置与环境依赖

### 5.1 必需的外部程序

- **VLC 播放器**：可选用两种方式：
  - 本地打包：将 `libvlc.dll`、`libvlccore.dll`、`plugins` 目录及 MinGW 运行时（`libgcc_s_seh-1.dll`, `libstdc++-6.dll`, `libwinpthread-1.dll`）放在程序同级的 `vlc` 文件夹内。
  - 系统安装：程序会自动查找系统 PATH 中的 VLC（若未找到本地 `vlc` 目录）。
- **ExifTool**：建议使用**静态编译的独立 exe**（下载 `exiftool-12.xx_64.zip` 中的 `exiftool.exe`），放置于程序同级的 `exiftool` 文件夹内，或系统 PATH 中。若使用依赖 Perl 环境的版本，需保留 `exiftool_files` 目录。

### 5.2 Python 依赖安装

```bash
pip install PyQt5 python-vlc pillow pillow-heif pyinstaller
```

### 5.3 可选组件

- **pillow-heif**：若不安装则无法打开 HEIC 文件，但其他格式正常。
- **ffmpeg**：程序不依赖，但系统若安装可提高 `video.png` 以外的视频缩略图生成（实际代码未使用）。

## 6. 打包部署

### 6.1 打包命令

在项目根目录执行：

```bash
pyinstaller --onefile --windowed --name APP13422 --add-data "vlc;vlc" --add-data "exiftool;exiftool" --add-data "Assets;Assets" --add-data "app.ico;." --icon app.ico main.py
```

### 6.2 打包注意事项

- **路径分隔符**：Windows 下 `--add-data` 使用分号 `;` 分隔源路径和目标路径。
- **VLC 插件加载**：打包后的 exe 启动时，`setup_vlc_env()` 会从 `sys._MEIPASS` 解压的临时文件夹中找到 `vlc` 目录，并设置 `PATH` 和 `VLC_PLUGIN_PATH`。**必须确保 `vlc` 目录下包含三个 MinGW 运行时 DLL**，否则 VLC 实例创建失败。
- **ExifTool 静态化**：推荐使用静态编译版 `exiftool.exe`，这样无需打包 `exiftool_files`，减少体积。
- **图标显示**：代码中已在导入 PyQt5 前调用 `SetCurrentProcessExplicitAppUserModelID`，打包后任务栏图标会正常显示为 `app.ico`。

### 6.3 运行测试

- 双击 `dist/APP13422.exe` 运行。
- 拖拽照片到 exe 图标上，应自动打开并加载该照片。
- 左侧文件列表、缩放、播放实况等功能应全部正常。

## 7. 常见问题调试

| 问题现象                             | 可能原因及解决方案                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------- |
| VLC 初始化失败，`vlc_instance` 为 None | 1. 本地 `vlc` 目录缺少 MinGW 运行时（`libgcc_s_seh-1.dll` 等）<br/>2. `plugins` 目录被破坏<br/>3. 系统未安装 VLC 且本地目录无效 |
| ExifTool 无法提取视频                 | 1. `exiftool.exe` 依赖 Perl 环境但 `exiftool_files` 缺失 → 改用静态编译版<br/>2. 照片不含内嵌视频标签 → 软件会提示“无实况视频” |
| HEIC 图片打不开                       | 未安装 `pillow-heif`，使用 `pip install pillow-heif` 安装即可（需先安装 VC++ 运行库） |
| 切换照片后 UI 卡死                    | 可能是前一个 VLC 实例未完全停止（状态仍为 Playing/Paused）。检查 `_stop_vlc_safely` 中的等待循环是否生效，或增加等待时长。 |
| 打包后 exe 体积过大（>200MB）          | 检查是否打包了不必要的文件（如 `.jar`、文档等）。VLC 可精简 `plugins` 目录，仅保留必需插件（参见 VLC 精简列表）。 |
| 任务栏图标仍为默认 Python 图标          | 确保代码中的 `SetCurrentProcessExplicitAppUserModelID` 在 `QApplication` 创建之前执行，且打包时 `--icon` 参数正确。 |

## 8. 扩展与定制

- **添加更多图片格式**：在 `exts` 集合中添加对应的扩展名（如 `.tif`、`.webp`），并确保 `load_image_pixmap` 能够解码。
- **修改工具栏溢出阈值**：调整 `self.temp_msg_label` 和 `self.file_info_label` 的固定宽度，或改为动态计算。
- **自定义视频封面**：替换 `Assets/video.png` 即可。
- **更改静音/音量图标**：修改 `mute_btn` 的文本和样式，使用 Qt 资源系统或自定义图标。
- **增加云同步/收藏功能**：可在文件列表基础上添加数据库，记录评分或标签（需要扩展数据模型和 UI）。

## 9. 版本历史

| 版本   | 日期       | 主要更新                                                                 |
| ------ | ---------- | ------------------------------------------------------------------------ |
| 1.0.0  | 2026-04-26 | 初始发布，支持实况视频提取、播放、缩放、文件列表、托盘、导出等功能。      |
| 1.0.1  | 2026-04-29 | 修复打包后 VLC 初始化失败、添加窗口图标支持、优化索引路径匹配。           |

## 10. 许可证与致谢

- **ExifTool** © Phil Harvey，遵循 Perl 艺术许可或 GPL。
- **VLC** © VideoLAN，遵循 GPL。
- **PyQt5** © Riverbank Computing，遵循 GPL。
- **Pillow** © 作者，遵循 MIT 许可。
- 本项目仅供个人学习与研究使用。

---

**文档结束**
