# 实况照片播放器（目前只适配了oppo，其他手机实况图尚未适配）
适配oppo手机拍摄的实况照片的照片播放器，可查看照片和里面的视频

项目完整代码与开发文档
一、项目简介
实况照片播放器 是一款基于 PyQt5 和 VLC 的桌面应用程序，专门用于播放 OPPO 等手机拍摄的“实况照片”（即内嵌短视频的 JPG/HEIC 文件）。支持实况视频提取与播放、常规图片/视频浏览、缩放拖拽、文件列表导航、系统托盘、导出照片/视频等功能。

主要特性：
支持格式：.jpg, .jpeg, .heic, .png, .bmp, .tiff 以及常见视频格式（.mp4, .avi, .mov 等）。
自动提取实况照片中的短视频（依赖 exiftool）。
视频播放控制：播放/暂停/停止、调速（0.25x ~ 2x）、静音。
图片查看：鼠标滚轮以光标为中心缩放、拖拽平移、双击适应窗口。
左侧可收展文件列表，支持文件夹内图片快速切换。
键盘导航：上下左右键切换图片，回车键播放/暂停。
系统托盘支持，关闭窗口最小化到托盘。
导出功能：导出当前照片（HEIC 自动转 JPEG）、导出内嵌视频。
完全本地化，无需互联网连接。

二、完整代码 (main.py)
见代码。

三、开发文档
3.1 环境要求
操作系统：Windows 7/8/10/11（64位）
Python 版本：3.8 ~ 3.13（推荐 3.10+）
依赖库：
text
PyQt5 >= 5.15.0
python-vlc >= 3.0.0
pillow >= 9.0.0
pillow-heif >= 0.10.0   (可选，用于 HEIC 支持)
pyinstaller >= 5.0      (用于打包)
3.2 项目结构
text
项目根目录/
├── main.py                # 主程序
├── app.ico                # 应用程序图标
├── Assets/                # 资源文件夹
│   └── video.png          # 视频占位图
├── exiftool/              # ExifTool 目录（可选，用于提取实况视频）
│   ├── exiftool.exe
│   └── exiftool_files/    # 依赖文件（若使用静态版 exiftool 可删）
└── vlc/                   # VLC 播放器目录（可选，若系统已安装可删除）
    ├── libvlc.dll
    ├── libvlccore.dll
    ├── libgcc_s_seh-1.dll
    ├── libstdc++-6.dll
    ├── libwinpthread-1.dll
    └── plugins/           # 插件目录（经过精简）
3.3 功能使用说明
基本操作
打开文件：点击工具栏 文件 → 打开文件，或直接拖拽图片/视频到窗口。
切换照片：使用键盘 ← → ↑ ↓ 或点击工具栏 上一张/下一张 按钮。
缩放图片：鼠标滚轮向上放大、向下缩小（已以光标为中心）。
拖动图片：放大后按住左键拖动。
播放实况：单击图片中间区域（适应窗口时）或点击工具栏 ⏯️ 播放 按钮。
暂停/停止：使用对应按钮或单击视频窗口。
调速：底部右侧 速度 下拉框选择（0.25~2倍速）。
静音：底部右侧 🔊 静音 按钮。
文件列表：点击 ☰ 文件列表 按钮显示/隐藏左侧列表，双击列表项切换照片。
导出：点击 导出照片 或 导出视频 将文件保存到程序根目录下的 导出照片/导出视频 文件夹。
系统托盘：关闭窗口后程序最小化到托盘，右键托盘图标可显示或退出。
3.4 打包为独立 EXE
使用 PyInstaller 打包，命令如下（在项目根目录执行）：
bash
pyinstaller --onefile --windowed --name APP13422 --add-data "vlc;vlc" --add-data "exiftool;exiftool" --add-data "Assets;Assets" --add-data "app.ico;." --icon app.ico main.py
参数说明：
--onefile：生成单个 exe。
--windowed：不显示控制台窗口。
--name APP13422：输出文件名。
--add-data "源路径;目标路径"：将文件夹打包进 exe。
--icon app.ico：设置 exe 文件图标。
打包后生成 dist/APP13422.exe，可独立运行。
3.5 常见问题
视频无法播放：请确保 VLC 目录完整或系统已安装 VLC。
实况视频提取失败：检查 exiftool 目录是否完整，或使用静态编译版 exiftool。
HEIC 图片无法打开：安装 pillow-heif 库：pip install pillow-heif。
任务栏图标不显示：打包后自动设置 AppUserModelID，无需额外操作。
拖拽到 exe 不打开图片：本程序已支持命令行参数，可直接拖拽文件到 exe 图标上。
3.6 日志文件
程序运行日志保存在 logs/live_photo_viewer.log，便于排查错误。
