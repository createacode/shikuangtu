#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPPO 实况图播放器 - 最终版
修复图标显示、所有功能完整
"""

import sys
import os
import subprocess
import tempfile
import logging
import shutil
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional
from datetime import datetime

# 必须在导入 PyQt5 之前设置 Windows 任务栏 AppUserModelID
if sys.platform == 'win32':
    import ctypes
    # 设置一个唯一的 AppUserModelID，确保任务栏图标正确显示
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('APP13422')

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QWidget, QVBoxLayout, QHBoxLayout,
    QStatusBar, QFileDialog, QMessageBox, QAction, QStackedWidget,
    QScrollArea, QToolBar, QPushButton, QComboBox, QMenu, QSizePolicy,
    QShortcut, QDockWidget, QListWidget, QListWidgetItem, QSystemTrayIcon,
    QAbstractItemView
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QEvent, QMutex, QMutexLocker, QPoint, QUrl, QCoreApplication
)
from PyQt5.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QColor, QPainter, QIcon,
    QDesktopServices, QImage, QKeySequence, QFont
)

# ---------- 日志配置 ----------
def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "live_photo_viewer.log"
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    fh = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

def resource_path(relative_path):
    """获取资源文件路径（支持PyInstaller打包）"""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_app_root():
    """获取可执行文件所在目录（用于导出文件夹）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

# ---------- VLC 环境 ----------
def setup_vlc_env():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    
    possible_dirs = [
        os.path.join(base_path, "vlc"),
        os.path.abspath("vlc"),
        os.path.join(os.path.dirname(sys.executable), "vlc")
    ]
    vlc_dir = None
    for d in possible_dirs:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "libvlc.dll")):
            vlc_dir = d
            break
            
    if vlc_dir:
        os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")
        plugins_dir = os.path.join(vlc_dir, "plugins")
        if os.path.isdir(plugins_dir):
            os.environ["VLC_PLUGIN_PATH"] = plugins_dir
        logger.info(f"使用本地 VLC: {vlc_dir}")
        return True
        
    logger.warning("未找到本地 VLC，将尝试系统 VLC")
    return False

setup_vlc_env()
import vlc

# ---------- exiftool ----------
def find_exiftool() -> Optional[str]:
    candidates = [
        resource_path(os.path.join("exiftool", "exiftool.exe")),
        os.path.join(get_app_root(), "exiftool", "exiftool.exe"),
        os.path.join(os.path.dirname(sys.executable), "exiftool", "exiftool.exe"),
        "exiftool.exe",
        "exiftool"
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            logger.info(f"找到 exiftool: {c}")
            return c
    # 尝试从当前工作目录
    local = os.path.join(os.getcwd(), "exiftool", "exiftool.exe")
    if os.path.isfile(local):
        logger.info(f"找到 exiftool (工作目录): {local}")
        return local
    logger.error("未找到 exiftool.exe")
    return None

def get_photo_date(path: str) -> str:
    logger.debug(f"读取照片日期: {path}")
    try:
        exiftool = find_exiftool()
        if exiftool:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                [exiftool, "-DateTimeOriginal", "-s3", path],
                capture_output=True, timeout=5, startupinfo=startupinfo,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                date_str = result.stdout.strip()
                if ' ' in date_str:
                    date_part, time_part = date_str.split(' ')
                    date_part = date_part.replace(':', '-')
                    return f"{date_part} {time_part}"
                else:
                    return date_str.replace(':', '-')
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
            img = Image.open(path)
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == 'DateTimeOriginal':
                        return value.replace(':', '-')
        except:
            pass
        return "未知日期"
    except Exception as e:
        logger.warning(f"读取日期失败: {e}")
        return "未知日期"

# ---------- HEIC 支持 ----------
HEIC_SUPPORT = False
try:
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
    logger.info("HEIC 支持已启用")
except ImportError:
    logger.warning("未安装 pillow-heif，无法打开 HEIC 文件")

def load_image_pixmap(path: str) -> Optional[QPixmap]:
    logger.debug(f"加载图片: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.heic', '.heif'):
        if HEIC_SUPPORT:
            try:
                img = Image.open(path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                data = img.tobytes("raw", "RGB")
                qimage = QImage(data, img.width, img.height, QImage.Format_RGB888)
                return QPixmap.fromImage(qimage)
            except Exception as e:
                logger.error(f"加载 HEIC 失败 {path}: {e}")
                return None
        else:
            return None
    else:
        pix = QPixmap(path)
        if not pix.isNull():
            logger.debug(f"普通图片加载成功: {path}")
        else:
            logger.warning(f"图片加载失败: {path}")
        return pix

# ---------- 导出照片线程 ----------
class PhotoExportThread(QThread):
    finished = pyqtSignal(str, bool)
    def __init__(self, src, dst):
        super().__init__()
        self.src = src
        self.dst = dst
    def run(self):
        logger.info(f"开始导出照片: {self.src} -> {self.dst}")
        try:
            ext = os.path.splitext(self.src)[1].lower()
            if ext in ('.heic', '.heif'):
                img = Image.open(self.src)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(self.dst, 'JPEG', quality=95)
            else:
                shutil.copy2(self.src, self.dst)
            self.finished.emit(self.dst, True)
            logger.info(f"照片导出成功: {self.dst}")
        except Exception as e:
            logger.error(f"导出照片失败: {e}")
            self.finished.emit("", False)

# ---------- 视频提取线程 ----------
class VideoExtractor(QThread):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str, str)
    def __init__(self, image_path, exiftool_path):
        super().__init__()
        self.image_path = image_path
        self.exiftool_path = exiftool_path
        self._stopped = False
        self.mutex = QMutex()
        logger.debug(f"创建视频提取线程: {image_path}")
    def stop(self):
        with QMutexLocker(self.mutex):
            self._stopped = True
        logger.debug(f"停止视频提取线程: {self.image_path}")
    def is_stopped(self):
        with QMutexLocker(self.mutex):
            return self._stopped
    def run(self):
        logger.info(f"开始从图片提取视频: {self.image_path}")
        tags = ["-MotionPhotoVideo", "-VideoFile", "-EmbeddedVideo"]
        for tag in tags:
            if self.is_stopped():
                return
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                result = subprocess.run(
                    [self.exiftool_path, "-b", tag, self.image_path],
                    capture_output=True, timeout=15, startupinfo=startupinfo, shell=False
                )
                if result.returncode == 0 and len(result.stdout) > 8 and result.stdout[4:8] == b'ftyp':
                    fd, temp_path = tempfile.mkstemp(suffix=".mp4", prefix="live_")
                    os.close(fd)
                    with open(temp_path, "wb") as f:
                        f.write(result.stdout)
                    logger.info(f"视频提取成功: {self.image_path} -> {temp_path}")
                    self.finished.emit(self.image_path, temp_path)
                    return
            except subprocess.TimeoutExpired:
                logger.error(f"提取超时 {self.image_path} tag {tag}")
            except Exception as e:
                logger.error(f"提取异常 {self.image_path}: {e}")
        logger.warning(f"未从 {self.image_path} 中找到内嵌视频")
        self.error.emit(self.image_path, "未找到内嵌视频")

# ========== 主窗口 ==========
class LivePhotoViewer(QMainWindow):
    video_end_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("实况照片播放器 - Copyright © 2026.4 XAF")
        self.setMinimumSize(600, 480)
        self.resize(665, 600)
        self.setAcceptDrops(True)
        
        # 设置窗口图标（打包后也能正确加载）
        ico_path = resource_path("app.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))
        else:
            logger.warning(f"图标文件未找到: {ico_path}")
        
        self.setFocusPolicy(Qt.StrongFocus)

        # 设置支持 Emoji 的字体
        emoji_font = QFont("Segoe UI Emoji")

        # 全局样式
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; margin: 0px; padding: 0px; }
            QStatusBar { background-color: #e8e8e8; color: #333333; font-size: 12px; border-top: 1px solid #dcdcdc; }
            QToolBar { background-color: #f0f0f0; border: none; spacing: 5px; }
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
            QPushButton:pressed {
                background-color: #c0c0c0;
                padding: 5px 7px 3px 9px;
            }
            QComboBox { background-color: white; border: 1px solid #cccccc; border-radius: 3px; padding: 2px; }
            QLabel#image_label { background-color: #eaeaea; }
            QListWidget {
                background-color: #fafafa;
                border: none;
                outline: none;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #e0e0e0;
            }
            QListWidget::item:selected {
                background-color: #d0d0d0;
                color: black;
            }
            QDockWidget::title {
                background-color: #e8e8e8;
                text-align: center;
                height: 25px;
            }
        """)

        # 系统托盘
        self.tray_icon = None
        self.create_tray_icon()

        # 初始化 VLC
        try:
            self.vlc_instance = vlc.Instance("--quiet", "--no-video-title-show", "--network-caching=300")
            if self.vlc_instance is None:
                # 尝试指定插件路径
                plugins_path = os.environ.get("VLC_PLUGIN_PATH", "")
                if plugins_path:
                    self.vlc_instance = vlc.Instance(f"--plugin-path={plugins_path}", "--quiet", "--no-video-title-show")
            if self.vlc_instance is None:
                raise RuntimeError("无法创建 VLC 实例")
            self.vlc_player = self.vlc_instance.media_player_new()
            self.vlc_volume = 50
            self.vlc_player.audio_set_volume(self.vlc_volume)
            logger.info("VLC 实例初始化成功")
        except Exception as e:
            logger.error(f"VLC 初始化错误: {e}")
            QMessageBox.critical(self, "错误", f"无法初始化 VLC 播放器: {e}")
            sys.exit(1)

        # 左侧文件列表
        self.file_list_dock = QDockWidget("文件列表", self)
        self.file_list_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.file_list_dock.setFixedWidth(200)
        self.file_list_widget = QListWidget()
        self.file_list_widget.itemClicked.connect(self.on_file_list_item_clicked)
        self.file_list_widget.setAutoScroll(False)
        self.file_list_dock.setWidget(self.file_list_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.file_list_dock)
        self.file_list_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.file_list_dock.hide()

        # 顶部工具栏
        self.toolbar = QToolBar("工具栏")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        self.file_btn = QPushButton("文件")
        self.file_btn.clicked.connect(self.show_file_menu)
        self.toolbar.addWidget(self.file_btn)

        self.toggle_list_btn = QPushButton("☰ 文件列表")
        self.toggle_list_btn.clicked.connect(self.toggle_file_list)
        self.toolbar.addWidget(self.toggle_list_btn)

        self.export_photo_btn = QPushButton("导出照片")
        self.export_video_btn = QPushButton("导出视频")
        self.open_screenshot_folder_btn = QPushButton("打开截图")
        self.open_video_folder_btn = QPushButton("打开视频")
        self.export_photo_btn.clicked.connect(self.export_photo)
        self.export_video_btn.clicked.connect(self.export_video_default)
        self.open_screenshot_folder_btn.clicked.connect(self.open_export_photo_folder)
        self.open_video_folder_btn.clicked.connect(self.open_export_video_folder)
        self.toolbar.addWidget(self.export_photo_btn)
        self.toolbar.addWidget(self.export_video_btn)
        self.toolbar.addWidget(self.open_screenshot_folder_btn)
        self.toolbar.addWidget(self.open_video_folder_btn)

        self.toolbar.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        self.temp_msg_label = QLabel("")
        self.temp_msg_label.setFixedWidth(150)
        self.toolbar.addWidget(self.temp_msg_label)

        self.file_info_label = QLabel("")
        self.file_info_label.setFixedWidth(320)
        self.file_info_label.setWordWrap(False)
        self.file_info_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.toolbar.addWidget(self.file_info_label)

        # 底部控制栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("background-color: #e8e8e8;")
        self.control_widget = QWidget()
        control_layout = QHBoxLayout(self.control_widget)
        control_layout.setContentsMargins(5, 2, 5, 2)
        control_layout.setSpacing(10)

        self.status_label = QLabel("就绪")
        self.status_label.setFont(emoji_font)
        self.status_label.setFixedWidth(200)
        control_layout.addWidget(self.status_label)

        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(20)
        self.btn_prev = QPushButton("上一张")
        self.btn_next = QPushButton("下一张")
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_next.clicked.connect(self.next_image)
        for btn in (self.btn_prev, self.btn_next):
            btn.setFixedSize(80, 36)
        middle_layout.addWidget(self.btn_prev)
        middle_layout.addWidget(self.btn_next)
        middle_layout.addSpacing(40)
        self.btn_play_pause = QPushButton("⏯️ 播放")
        self.btn_play_pause.setFixedSize(100, 30)
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        self.btn_stop = QPushButton("⏹️ 停止")
        self.btn_stop.setFixedSize(80, 30)
        self.btn_stop.clicked.connect(self.stop_control)
        middle_layout.addWidget(self.btn_play_pause)
        middle_layout.addWidget(self.btn_stop)

        control_layout.addStretch()
        control_layout.addLayout(middle_layout)
        control_layout.addStretch()

        # 右侧速度+静音
        self.right_layout = right_layout = QHBoxLayout()
        right_layout.setSpacing(10)
        self.speed_combo = QComboBox()
        speeds = ["0.25", "0.5", "0.75", "1", "1.25", "1.5", "2"]
        self.speed_combo.addItems(speeds)
        self.speed_combo.setCurrentText("1")
        self.speed_combo.setFixedWidth(70)
        self.speed_combo.setEditable(False)
        self.speed_combo.currentTextChanged.connect(self.change_playback_speed)
        self.mute_btn = QPushButton("🔊 静音")
        self.mute_btn.setFixedSize(80, 30)
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.is_muted = False
        self.last_volume = 50
        right_layout.addWidget(QLabel("速度:"))
        right_layout.addWidget(self.speed_combo)
        right_layout.addWidget(self.mute_btn)
        control_layout.addLayout(right_layout)
        self.status_bar.addWidget(self.control_widget)

        # 中央区域
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("border: none; background-color: #eaeaea;")
        self.image_label = QLabel()
        self.image_label.setObjectName("image_label")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.scroll_area.setWidget(self.image_label)
        self.stacked_widget.addWidget(self.scroll_area)
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: black;")
        container_layout = QVBoxLayout(self.video_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_widget.setAttribute(Qt.WA_NativeWindow, True)
        container_layout.addWidget(self.video_widget, alignment=Qt.AlignCenter)
        self.stacked_widget.addWidget(self.video_container)

        # 状态变量
        self.current_image_path = None
        self.current_temp_video = None
        self.current_extractor_thread = None
        self.export_thread = None
        self.is_playing = False
        self.is_video_file = False
        self.video_original_size = None
        self._play_lock = QMutex()
        self._is_switching = False
        self._closing = False
        self.current_folder_images = []
        self.current_index = -1

        # 缩放相关
        self.original_pixmap = None
        self.current_scale = 1.0
        self.fit_scale = 1.0
        self.is_dragging = False
        self.drag_start_pos = QPoint()
        self.drag_scroll_values = (0, 0)

        # VLC 回调
        self.video_end_signal.connect(self._on_video_end_safe)
        self.event_manager = self.vlc_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_callback)

        # 事件过滤器
        self.image_label.installEventFilter(self)
        self.scroll_area.installEventFilter(self)
        self.video_container.installEventFilter(self)

        # 全局快捷键
        self.shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.shortcut_left.activated.connect(self.prev_image)
        self.shortcut_left.setContext(Qt.ApplicationShortcut)
        self.shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.shortcut_right.activated.connect(self.next_image)
        self.shortcut_right.setContext(Qt.ApplicationShortcut)
        self.shortcut_up = QShortcut(QKeySequence(Qt.Key_Up), self)
        self.shortcut_up.activated.connect(self.prev_image)
        self.shortcut_up.setContext(Qt.ApplicationShortcut)
        self.shortcut_down = QShortcut(QKeySequence(Qt.Key_Down), self)
        self.shortcut_down.activated.connect(self.next_image)
        self.shortcut_down.setContext(Qt.ApplicationShortcut)
        self.shortcut_enter = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.shortcut_enter.activated.connect(self.toggle_play_pause)
        self.shortcut_enter.setContext(Qt.ApplicationShortcut)
        self.shortcut_enter2 = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.shortcut_enter2.activated.connect(self.toggle_play_pause)
        self.shortcut_enter2.setContext(Qt.ApplicationShortcut)

        self.temp_files = []
        self.show_placeholder()
        logger.info("主窗口初始化完成")

    # ---------- 文件按钮菜单 ----------
    def show_file_menu(self):
        menu = QMenu(self)
        open_file = menu.addAction("打开文件")
        open_folder = menu.addAction("打开文件夹")
        menu.addSeparator()
        exit_action = menu.addAction("退出")
        open_file.triggered.connect(self.open_file_dialog)
        open_folder.triggered.connect(self.open_folder_dialog)
        exit_action.triggered.connect(self.quit_app)
        menu.exec_(self.file_btn.mapToGlobal(self.file_btn.rect().bottomLeft()))

    # ---------- 系统托盘 ----------
    def create_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        ico_path = resource_path("app.ico")
        icon = QIcon(ico_path) if os.path.exists(ico_path) else QIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("实况照片播放器")
        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_normal)
        quit_action = QAction("彻底退出", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()
    def show_normal(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
    def quit_app(self):
        logger.info("用户通过托盘/右键菜单退出程序")
        self._closing = True
        if self.tray_icon:
            self.tray_icon.hide()
        self.close()
        QApplication.quit()
    def closeEvent(self, event):
        if self.tray_icon and self.tray_icon.isVisible() and not self._closing:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage("实况照片播放器", "程序已最小化到系统托盘", QSystemTrayIcon.Information, 1000)
            logger.info("程序最小化到系统托盘")
            return
        logger.info("程序彻底关闭")
        self._full_stop_and_reset()
        for temp in self.temp_files:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
                    logger.debug(f"删除临时文件: {temp}")
            except Exception as e:
                logger.warning(f"清理临时文件失败 {temp}: {e}")
        event.accept()

    # ---------- 左侧文件列表 ----------
    def toggle_file_list(self):
        if self.file_list_dock.isVisible():
            self.file_list_dock.hide()
            logger.debug("隐藏文件列表")
        else:
            self.file_list_dock.show()
            logger.debug("显示文件列表")
    def update_file_list(self, folder_path=None, highlight_path=None):
        if folder_path is None and self.current_image_path:
            folder_path = os.path.dirname(self.current_image_path)
        if not folder_path or not os.path.isdir(folder_path):
            self.file_list_widget.clear()
            return
        exts = {'.jpg','.jpeg','.JPG','.JPEG','.heic','.HEIC','.png','.PNG','.bmp','.tiff'}
        images = []
        for f in os.listdir(folder_path):
            if any(f.lower().endswith(ext) for ext in exts):
                images.append(os.path.join(folder_path, f))
        images.sort()
        self.current_folder_images = images
        old_row = self.file_list_widget.currentRow()
        self.file_list_widget.clear()
        norm_highlight = os.path.normpath(highlight_path) if highlight_path else None
        norm_current = os.path.normpath(self.current_image_path) if self.current_image_path else None
        for idx, img_path in enumerate(images):
            item = QListWidgetItem(os.path.basename(img_path))
            item.setData(Qt.UserRole, img_path)
            self.file_list_widget.addItem(item)
            norm_img = os.path.normpath(img_path)
            if (norm_highlight and norm_img == norm_highlight) or (norm_current and norm_img == norm_current):
                self.file_list_widget.setCurrentItem(item)
                self.file_list_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        if old_row >= 0 and old_row < self.file_list_widget.count():
            self.file_list_widget.scrollToItem(self.file_list_widget.item(old_row), QAbstractItemView.PositionAtCenter)
        logger.debug(f"文件列表已更新，共 {len(images)} 个文件")
    def on_file_list_item_clicked(self, item):
        img_path = item.data(Qt.UserRole)
        if img_path and os.path.exists(img_path):
            logger.info(f"从文件列表打开: {img_path}")
            self.open_path(img_path)

    # ---------- 拖拽 ----------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.exists(path):
                logger.info(f"拖拽文件: {path}")
                self.open_path(path)
                break

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_file = menu.addAction("打开文件")
        open_folder = menu.addAction("打开文件夹")
        menu.addSeparator()
        prev = menu.addAction("上一张")
        next_ = menu.addAction("下一张")
        menu.addSeparator()
        export_photo = menu.addAction("导出照片")
        export_video = menu.addAction("导出视频...")
        menu.addSeparator()
        toggle_list = menu.addAction("显示/隐藏文件列表")
        close_img = menu.addAction("关闭图片")
        exit_act = menu.addAction("退出")
        open_file.triggered.connect(self.open_file_dialog)
        open_folder.triggered.connect(self.open_folder_dialog)
        prev.triggered.connect(self.prev_image)
        next_.triggered.connect(self.next_image)
        export_photo.triggered.connect(self.export_photo)
        export_video.triggered.connect(self.export_video_custom)
        toggle_list.triggered.connect(self.toggle_file_list)
        close_img.triggered.connect(self.close_current_image)
        exit_act.triggered.connect(self.quit_app)
        menu.exec_(event.globalPos())

    def show_temp_message(self, msg, timeout=3000):
        self.temp_msg_label.setText(msg)
        QTimer.singleShot(timeout, lambda: self.temp_msg_label.setText(""))
    def update_file_info(self, path):
        if not path or not os.path.exists(path):
            self.file_info_label.setText("")
            return
        name = os.path.basename(path)
        size = os.path.getsize(path)
        if size < 1024:
            s = f"{size}B"
        elif size < 1024*1024:
            s = f"{size/1024:.1f}KB"
        else:
            s = f"{size/(1024*1024):.1f}MB"
        date = get_photo_date(path)
        self.file_info_label.setText(f"{name} | {s} | 📅 {date}")
        logger.debug(f"更新文件信息: {name} {s} {date}")
    def show_placeholder(self):
        pix = QPixmap(600,400)
        pix.fill(QColor("#eaeaea"))
        p = QPainter(pix)
        p.setPen(QColor("#666666"))
        font = p.font()
        font.setPointSize(12)
        p.setFont(font)
        p.drawText(pix.rect(), Qt.AlignCenter,
            "实况照片播放器\n支持 OPPO 实况照片、HEIC、常规图片、视频\n\n"
            "✨ 操作说明：\n"
            "• 拖拽或打开图片/视频文件\n"
            "• 右键菜单：打开/导航/导出\n"
            "• 鼠标滚轮以光标为中心缩放\n"
            "• 键盘 ←/→ 或 ↑/↓ 切换，回车播放/暂停\n"
            "• 单击图片左1/3→上一张，右1/3→下一张，中间→播放\n"
            "• 左侧文件列表可打开/关闭，点击即可切换照片")
        p.end()
        self.set_image_pixmap(pix, reset_zoom=False)
        self.status_label.setText("就绪")
        self.current_image_path = None
        self.file_info_label.setText("")
        self.file_list_widget.clear()

    # ---------- 图片显示与缩放 ----------
    def set_image_pixmap(self, pixmap: QPixmap, reset_zoom=True):
        self.original_pixmap = pixmap
        if reset_zoom:
            self._update_fit_scale()
            self.current_scale = self.fit_scale
            self._apply_scale()
        else:
            if self.original_pixmap:
                scaled = self.original_pixmap.scaled(
                    int(self.original_pixmap.width() * self.current_scale),
                    int(self.original_pixmap.height() * self.current_scale),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)
                self.image_label.setFixedSize(scaled.size())
    def _update_fit_scale(self):
        if not self.original_pixmap:
            return
        vs = self.scroll_area.viewport().size()
        w = self.original_pixmap.width()
        h = self.original_pixmap.height()
        if w == 0 or h == 0:
            self.fit_scale = 1.0
        else:
            self.fit_scale = min(vs.width()/w, vs.height()/h)
            self.fit_scale = max(0.1, min(10.0, self.fit_scale))
    def _apply_scale(self, anchor=None):
        if not self.original_pixmap:
            return
        old = self.image_label.size()
        new_w = max(10, int(self.original_pixmap.width() * self.current_scale))
        new_h = max(10, int(self.original_pixmap.height() * self.current_scale))
        scaled = self.original_pixmap.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedSize(new_w, new_h)
        if anchor and old.width()>0 and old.height()>0:
            vr = self.scroll_area.viewport().rect()
            ax = self.scroll_area.horizontalScrollBar().value() + anchor.x()
            ay = self.scroll_area.verticalScrollBar().value() + anchor.y()
            rx = ax / old.width()
            ry = ay / old.height()
            nx = rx * new_w
            ny = ry * new_h
            hb = max(0, min(nx - vr.width()*rx, new_w - vr.width()))
            vb = max(0, min(ny - vr.height()*ry, new_h - vr.height()))
            self.scroll_area.horizontalScrollBar().setValue(int(hb))
            self.scroll_area.verticalScrollBar().setValue(int(vb))
        elif abs(self.current_scale - self.fit_scale) < 0.001:
            self._center_scroll()
    def _center_scroll(self):
        QTimer.singleShot(10, lambda: self.scroll_area.ensureVisible(
            self.image_label.width()//2, self.image_label.height()//2))
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 底部右侧控件动态隐藏/显示，阈值 800
        if hasattr(self, 'control_widget'):
            width = self.control_widget.width()
            hide = width < 800
            if hide:
                if self.speed_combo.isVisible():
                    self.speed_combo.hide()
                    self.mute_btn.hide()
                    for i in range(self.right_layout.count()):
                        w = self.right_layout.itemAt(i).widget()
                        if isinstance(w, QLabel) and w.text() == "速度:":
                            w.hide()
                            break
            else:
                if not self.speed_combo.isVisible():
                    self.speed_combo.show()
                    self.mute_btn.show()
                    for i in range(self.right_layout.count()):
                        w = self.right_layout.itemAt(i).widget()
                        if isinstance(w, QLabel) and w.text() == "速度:":
                            w.show()
                            break
        if self.stacked_widget.currentWidget() == self.scroll_area and self.original_pixmap:
            old = self.fit_scale
            self._update_fit_scale()
            if abs(self.current_scale - old) < 0.001:
                self.current_scale = self.fit_scale
            self._apply_scale()
        elif self.stacked_widget.currentWidget() == self.video_container and self.is_playing and self.video_original_size:
            self._resize_video_widget()
    def can_zoom(self):
        return self.current_image_path is not None and self.original_pixmap is not None
    def zoom_in(self, pos_global=None):
        if not self.can_zoom(): return
        anchor = None
        if pos_global:
            local = self.image_label.mapFromGlobal(pos_global)
            if 0 <= local.x() <= self.image_label.width() and 0 <= local.y() <= self.image_label.height():
                anchor = local
        self.current_scale = min(self.current_scale * 1.05, 10.0)
        self._apply_scale(anchor)
        logger.debug(f"放大图片，缩放比例: {self.current_scale:.2f}")
    def zoom_out(self, pos_global=None):
        if not self.can_zoom(): return
        anchor = None
        if pos_global:
            local = self.image_label.mapFromGlobal(pos_global)
            if 0 <= local.x() <= self.image_label.width() and 0 <= local.y() <= self.image_label.height():
                anchor = local
        new = self.current_scale / 1.05
        self.current_scale = new if new >= self.fit_scale else self.fit_scale
        self._apply_scale(anchor)
        logger.debug(f"缩小图片，缩放比例: {self.current_scale:.2f}")
    def zoom_fit(self):
        if not self.can_zoom(): return
        self.current_scale = self.fit_scale
        self._apply_scale()
        logger.debug("恢复适应窗口大小")
    def eventFilter(self, source, event):
        if source == self.scroll_area and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self.current_image_path and self.current_scale <= self.fit_scale + 0.001:
                pos = self.image_label.mapFromGlobal(event.globalPos())
                if self.image_label.rect().contains(pos):
                    w = self.image_label.width()
                    if w > 0:
                        x = pos.x()
                        if x < w // 3:
                            self.prev_image()
                        elif x > (w * 2) // 3:
                            self.next_image()
                        else:
                            self.toggle_play_pause()
                        return True
            return False
        if source == self.image_label:
            if event.type() == QEvent.Wheel and self.can_zoom():
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_in(event.globalPos())
                else:
                    self.zoom_out(event.globalPos())
                return True
            if event.type() == QEvent.MouseButtonDblClick and self.can_zoom():
                self.zoom_fit()
                return True
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if self.can_zoom() and self.current_scale > self.fit_scale + 0.001:
                    self.is_dragging = True
                    self.drag_start_pos = event.pos()
                    self.drag_scroll_values = (self.scroll_area.horizontalScrollBar().value(),
                                               self.scroll_area.verticalScrollBar().value())
                    self.image_label.setCursor(Qt.ClosedHandCursor)
                    return True
                else:
                    if self.current_image_path and not self.is_playing:
                        w = self.image_label.width()
                        x = event.pos().x()
                        if w > 0 and w//3 <= x <= (w*2)//3:
                            self.toggle_play_pause()
                    return True
            if event.type() == QEvent.MouseMove and self.is_dragging:
                if not self.image_label.rect().contains(event.pos()):
                    self.is_dragging = False
                    self.image_label.setCursor(Qt.ArrowCursor)
                    return True
                delta = event.pos() - self.drag_start_pos
                h = self.scroll_area.horizontalScrollBar()
                v = self.scroll_area.verticalScrollBar()
                nh = max(0, min(self.drag_scroll_values[0] - delta.x(), h.maximum()))
                nv = max(0, min(self.drag_scroll_values[1] - delta.y(), v.maximum()))
                h.setValue(nh)
                v.setValue(nv)
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self.is_dragging:
                self.is_dragging = False
                self.image_label.setCursor(Qt.ArrowCursor)
                return True
        if source == self.video_container and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.toggle_play_pause()
            return True
        return super().eventFilter(source, event)

    # ---------- 导航 ----------
    def scan_folder_images(self, current_path):
        folder = os.path.dirname(current_path)
        exts = {'.jpg','.jpeg','.JPG','.JPEG','.heic','.HEIC','.png','.PNG','.bmp','.tiff'}
        images = []
        for f in os.listdir(folder):
            if any(f.lower().endswith(ext) for ext in exts):
                images.append(os.path.join(folder, f))
        images.sort()
        self.current_folder_images = images
        norm_current = os.path.normpath(current_path)
        try:
            self.current_index = images.index(norm_current)
        except ValueError:
            norm_images = [os.path.normpath(p) for p in images]
            try:
                self.current_index = norm_images.index(norm_current)
            except ValueError:
                self.current_index = -1
        self.update_file_list(folder, current_path)
        logger.info(f"扫描文件夹 {folder}，共 {len(images)} 个图片文件，当前索引 {self.current_index}")
    def load_image_by_index(self, index):
        if 0 <= index < len(self.current_folder_images):
            logger.info(f"切换到索引 {index}: {self.current_folder_images[index]}")
            self.open_path(self.current_folder_images[index])
        else:
            self.show_temp_message("已是第一张图片" if index < 0 else "已是最后一张图片")
    def prev_image(self):
        if self.current_index > 0:
            self.load_image_by_index(self.current_index - 1)
        else:
            self.show_temp_message("已是第一张图片")
    def next_image(self):
        if self.current_index < len(self.current_folder_images) - 1:
            self.load_image_by_index(self.current_index + 1)
        else:
            self.show_temp_message("已是最后一张图片")
    def close_current_image(self):
        logger.info("关闭当前图片")
        self._full_stop_and_reset()
        self.current_image_path = None
        self.current_temp_video = None
        self.is_video_file = False
        self.current_folder_images = []
        self.current_index = -1
        self.original_pixmap = None
        self.show_placeholder()
        self.status_label.setText("就绪")
        self.show_temp_message("图片已关闭")

    def open_initial_file(self, file_path):
        """延迟打开初始文件，确保界面已显示"""
        if os.path.exists(file_path):
            QTimer.singleShot(100, lambda: self.open_path(file_path))

    # ---------- 导出照片/视频 ----------
    def export_photo(self):
        if not self.current_image_path or self.is_video_file:
            self.show_temp_message("没有可导出的照片", 1500)
            return
        target_dir = os.path.join(get_app_root(), "导出照片")
        os.makedirs(target_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(self.current_image_path)
        name, ext = os.path.splitext(base)
        if ext.lower() in ('.heic','.heif'):
            dst = os.path.join(target_dir, f"{name}_{ts}.jpg")
        else:
            dst = os.path.join(target_dir, f"{name}_{ts}{ext}")
        logger.info(f"导出照片: {self.current_image_path} -> {dst}")
        self.export_thread = PhotoExportThread(self.current_image_path, dst)
        self.export_thread.finished.connect(self.on_photo_export_finished)
        self.export_thread.start()
        self.show_temp_message("正在导出照片...", 1000)
    def on_photo_export_finished(self, dst, ok):
        if ok:
            self.show_temp_message(f"照片已导出: {os.path.basename(dst)}", 3000)
            logger.info(f"照片导出成功: {dst}")
        else:
            self.show_temp_message("导出照片失败", 2000)
            logger.error("照片导出失败")
    def export_video_default(self):
        if not self.current_image_path:
            self.show_temp_message("没有打开的文件", 1500)
            return
        self._export_video_to_folder(get_app_root())
    def export_video_custom(self):
        if not self.current_image_path:
            self.show_temp_message("没有打开的文件", 1500)
            return
        folder = QFileDialog.getExistingDirectory(self, "选择导出文件夹")
        if folder:
            self._export_video_to_folder(folder)
    def _export_video_to_folder(self, folder):
        logger.info(f"导出视频到文件夹: {folder}")
        if self.is_video_file:
            src = self.current_image_path
            if not os.path.exists(src):
                self.show_temp_message("原视频不存在", 1500)
                return
            target = os.path.join(folder, "导出视频")
            os.makedirs(target, exist_ok=True)
            dst = os.path.join(target, os.path.basename(src))
            shutil.copy2(src, dst)
            self.show_temp_message(f"视频已导出: {os.path.basename(dst)}", 3000)
            logger.info(f"视频导出成功: {dst}")
        else:
            exif = find_exiftool()
            if not exif:
                QMessageBox.critical(self, "错误", "未找到exiftool")
                return
            data = None
            for tag in ["-MotionPhotoVideo","-VideoFile","-EmbeddedVideo"]:
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = subprocess.SW_HIDE
                    r = subprocess.run([exif,"-b",tag,self.current_image_path], capture_output=True, timeout=10, startupinfo=si)
                    if r.returncode == 0 and len(r.stdout) > 8 and r.stdout[4:8] == b'ftyp':
                        data = r.stdout
                        break
                except:
                    continue
            if data:
                target = os.path.join(folder, "导出视频")
                os.makedirs(target, exist_ok=True)
                base = os.path.basename(self.current_image_path)
                name,_ = os.path.splitext(base)
                dst = os.path.join(target, f"{name}_video.mp4")
                with open(dst, "wb") as f:
                    f.write(data)
                self.show_temp_message(f"视频已导出: {os.path.basename(dst)}", 3000)
                logger.info(f"视频导出成功: {dst}")
            else:
                self.show_temp_message("未找到内嵌视频", 2000)
                logger.warning("未找到内嵌视频数据")
    def open_export_photo_folder(self):
        folder = os.path.join(get_app_root(), "导出照片")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        logger.debug(f"打开导出照片文件夹: {folder}")
    def open_export_video_folder(self):
        folder = os.path.join(get_app_root(), "导出视频")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        logger.debug(f"打开导出视频文件夹: {folder}")

    # ---------- 静音 ----------
    def toggle_mute(self):
        if not self.is_muted:
            self.last_volume = self.vlc_player.audio_get_volume()
            self.vlc_player.audio_set_volume(0)
            self.is_muted = True
            self.mute_btn.setText("🔇 取消静音")
            self.show_temp_message("已静音", 1000)
            logger.info("静音")
        else:
            self.vlc_player.audio_set_volume(self.last_volume)
            self.is_muted = False
            self.mute_btn.setText("🔊 静音")
            self.show_temp_message("已取消静音", 1000)
            logger.info("取消静音")

    # ---------- 播放控制 ----------
    def update_play_pause_button(self, playing):
        if playing:
            self.btn_play_pause.setText("⏯️ 暂停")
        else:
            self.btn_play_pause.setText("⏯️ 播放")
    def toggle_play_pause(self):
        with QMutexLocker(self._play_lock):
            if self._is_switching:
                return
            if not self.current_image_path:
                return
            if self.is_playing:
                state = self.vlc_player.get_state()
                if state == vlc.State.Playing:
                    self.vlc_player.pause()
                    self.status_label.setText("⏸️ 已暂停")
                    self.update_play_pause_button(False)
                    logger.info("暂停播放")
                elif state == vlc.State.Paused:
                    self.vlc_player.play()
                    self.status_label.setText("▶️ 播放中...")
                    self.update_play_pause_button(True)
                    logger.info("恢复播放")
            else:
                if self.is_video_file:
                    if self.current_image_path and os.path.exists(self.current_image_path):
                        logger.info("开始播放视频文件")
                        self._play_video_file_unsafe(self.current_image_path)
                else:
                    if self.current_temp_video and os.path.exists(self.current_temp_video):
                        logger.info("开始播放实况视频")
                        self._play_video_file_unsafe(self.current_temp_video)
                    else:
                        self.show_temp_message("无实况视频", 1500)
                        logger.info("尝试播放但无实况视频")
    def stop_control(self):
        with QMutexLocker(self._play_lock):
            if self._is_switching:
                return
            if self.is_playing:
                logger.info("停止播放")
                self._stop_vlc_safely()
                self.stacked_widget.setCurrentWidget(self.scroll_area)
                self.status_label.setText("⏹️ 已停止")
                self.update_play_pause_button(False)
    def _play_video_file_unsafe(self, video_path):
        if self._is_switching or self._closing:
            return
        try:
            self.stacked_widget.setCurrentWidget(self.video_container)
            win_id = int(self.video_widget.winId())
            self.vlc_player.set_hwnd(win_id)
            media = self.vlc_instance.media_new(video_path)
            self.vlc_player.set_media(media)
            self.vlc_player.play()
            QTimer.singleShot(10, self._get_video_size_after_play)
            self.is_playing = True
            sp = float(self.speed_combo.currentText())
            self.vlc_player.set_rate(sp)
            self.status_label.setText("▶️ 播放中...")
            self.update_play_pause_button(True)
            if self.is_muted:
                self.vlc_player.audio_set_volume(0)
            else:
                self.vlc_player.audio_set_volume(self.last_volume)
            logger.info(f"播放视频文件: {video_path}")
        except Exception as e:
            logger.error(f"播放失败: {e}")
            self.status_label.setText("❌ 播放失败")
            self.is_playing = False
    def _stop_vlc_safely(self):
        if not self.vlc_player:
            return
        try:
            self.vlc_player.stop()
            for _ in range(50):
                if self.vlc_player.get_state() == vlc.State.Stopped:
                    break
                QCoreApplication.processEvents()
                QThread.msleep(20)
            self.vlc_player.set_media(None)
        except Exception as e:
            logger.error(f"停止播放异常: {e}")
    def _full_stop_and_reset(self):
        with QMutexLocker(self._play_lock):
            self._is_switching = True
            try:
                if self.is_playing:
                    self._stop_vlc_safely()
                self.is_playing = False
                self.video_original_size = None
                if self.current_extractor_thread and self.current_extractor_thread.isRunning():
                    self.current_extractor_thread.stop()
                    self.current_extractor_thread.wait(1000)
                    self.current_extractor_thread = None
                self.stacked_widget.setCurrentWidget(self.scroll_area)
                self.speed_combo.setCurrentText("1")
                self.update_play_pause_button(False)
                logger.debug("播放状态已完全重置")
            finally:
                self._is_switching = False
    def change_playback_speed(self, speed_str):
        if not self.is_playing:
            return
        try:
            speed = float(speed_str)
            self.vlc_player.set_rate(speed)
            logger.debug(f"播放速度设置为 {speed}")
        except Exception as e:
            logger.warning(f"设置播放速度失败: {e}")

    # ---------- 打开/播放核心 ----------
    def open_path(self, path):
        if self._closing or self._is_switching:
            return
        logger.info(f"打开文件: {path}")
        self._full_stop_and_reset()
        low = path.lower()
        if low.endswith(('.mp4','.avi','.mov','.mkv')):
            self.current_image_path = path
            self.is_video_file = True
            self.current_temp_video = path
            self.display_video_thumbnail()
            self.update_file_info(path)
            self.scan_folder_images(path)
            with QMutexLocker(self._play_lock):
                self._play_video_file_unsafe(path)
            self.status_label.setText("🎬 视频文件")
        elif low.endswith(('.jpg','.jpeg','.heic','.png','.bmp','.tiff')):
            self.current_image_path = path
            self.is_video_file = False
            self.current_temp_video = None
            self.display_image(path)
            self.update_file_info(path)
            self.scan_folder_images(path)
            exif = find_exiftool()
            if not exif:
                self.status_label.setText("⚠️ 未找到 exiftool")
                logger.error("未找到 exiftool，无法提取视频")
                return
            self.current_extractor_thread = VideoExtractor(path, exif)
            self.current_extractor_thread.finished.connect(self.on_video_extracted)
            self.current_extractor_thread.error.connect(self.on_video_extract_error)
            self.current_extractor_thread.start()
            self.status_label.setText("🔍 检测实况数据...")
        else:
            self.status_label.setText("❌ 不支持的文件类型")
            logger.warning(f"不支持的文件类型: {path}")
    def display_video_thumbnail(self):
        cover = os.path.join(get_app_root(), "Assets", "video.png")
        if os.path.exists(cover):
            pix = QPixmap(cover)
            if not pix.isNull():
                vs = self.scroll_area.viewport().size()
                tw = max(150, int(vs.width() * 0.2))
                th = max(150, int(vs.height() * 0.2))
                scaled = pix.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                self.image_label.setFixedSize(scaled.size())
                self.original_pixmap = None
                self.current_scale = 1.0
                self.fit_scale = 1.0
                logger.debug(f"显示视频缩略图: {cover}")
                return
        self.display_image_placeholder("视频文件\n单击播放")
        logger.debug("未找到视频缩略图，显示占位符")
    def display_image_placeholder(self, text):
        pix = QPixmap(400,300)
        pix.fill(QColor("#eaeaea"))
        p = QPainter(pix)
        p.setPen(QColor("#666666"))
        p.drawText(pix.rect(), Qt.AlignCenter, text)
        p.end()
        self.set_image_pixmap(pix)
    def display_image(self, path):
        pix = load_image_pixmap(path)
        if pix and not pix.isNull():
            self.set_image_pixmap(pix)
        else:
            self.display_image_placeholder("图片加载失败")
    def _get_video_size_after_play(self):
        if self.vlc_player.get_state() in (vlc.State.Playing, vlc.State.Paused):
            w = self.vlc_player.video_get_width()
            h = self.vlc_player.video_get_height()
            if w > 0 and h > 0:
                self.video_original_size = (w, h)
                self._resize_video_widget()
                logger.debug(f"获取视频尺寸: {w}x{h}")
            else:
                QTimer.singleShot(10, self._get_video_size_after_play)
        else:
            QTimer.singleShot(10, self._get_video_size_after_play)
    def _resize_video_widget(self):
        if not self.video_original_size:
            return
        ow, oh = self.video_original_size
        cs = self.video_container.size()
        if cs.width() <= 0 or cs.height() <= 0:
            return
        r = min(cs.width()/ow, cs.height()/oh)
        nw = max(int(ow * r), 10)
        nh = max(int(oh * r), 10)
        self.video_widget.setFixedSize(nw, nh)
        logger.debug(f"调整视频控件大小: {nw}x{nh}")

    # ---------- 提取回调 ----------
    def on_video_extracted(self, img_path, temp_path):
        if img_path == self.current_image_path and not self.is_video_file:
            self.current_temp_video = temp_path
            self.temp_files.append(temp_path)
            self.status_label.setText("✅ 实况视频就绪")
            logger.info(f"实况视频已就绪: {temp_path}")
    def on_video_extract_error(self, img_path, err):
        if img_path == self.current_image_path:
            self.status_label.setText(err)
            logger.warning(f"实况视频提取失败: {err}")

    # ---------- VLC 回调 ----------
    def _on_vlc_end_callback(self, event):
        self.video_end_signal.emit()
    def _on_video_end_safe(self):
        with QMutexLocker(self._play_lock):
            self.is_playing = False
            self.stacked_widget.setCurrentWidget(self.scroll_area)
            self.status_label.setText("⏹️ 播放结束")
            self.update_play_pause_button(False)
            logger.info("视频播放结束")

    # ---------- 文件对话框 ----------
    def open_file_dialog(self):
        path,_ = QFileDialog.getOpenFileName(self, "打开文件", "",
            "图片文件 (*.jpg *.jpeg *.heic *.png *.bmp *.tiff);;视频文件 (*.mp4 *.avi *.mov)")
        if path:
            self.open_path(path)
    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.load_first_image_in_folder(folder)
    def load_first_image_in_folder(self, folder):
        exts = ['.jpg','.jpeg','.heic','.png']
        imgs = []
        for e in exts:
            imgs.extend(Path(folder).glob(f"*{e}"))
            imgs.extend(Path(folder).glob(f"*{e.upper()}"))
        if imgs:
            self.open_path(str(sorted(imgs)[0]))

if __name__ == "__main__":
    # 设置 Windows 任务栏 AppUserModelID（确保图标显示）
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('APP13422')
        except Exception:
            pass
    app = QApplication(sys.argv)
    viewer = LivePhotoViewer()
    viewer.show()
    
    # 处理命令行传入的文件（拖拽到exe或快捷方式）
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        # 延迟打开，确保窗口完全初始化
        QTimer.singleShot(200, lambda: viewer.open_initial_file(file_path))
    
    sys.exit(app.exec_())
