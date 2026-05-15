#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import sys
import json
import html
if sys.platform != "win32":
    import fcntl
import struct
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

_lock_fh = None  # set in main(); kept global so _restart_manager() can release it

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSystemTrayIcon, QMenu,
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QTextEdit, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QGroupBox, QFormLayout, QScrollArea,
    QMessageBox, QListWidget, QListWidgetItem,
    QInputDialog, QTimeEdit, QFileDialog, QProgressBar,
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen, QFont
from PyQt6.QtCore import Qt, QTime, QTimer, QProcess, QProcessEnvironment, pyqtSignal

# ---------------------------------------------------------------------------
# Install config — all paths derived from install.json next to this script
# ---------------------------------------------------------------------------

def _load_install_config() -> dict:
    config_path = Path(__file__).parent / "install.json"
    if not config_path.exists():
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Not Configured",
                "install.json not found.\nPlease run the Enshrouded Server Manager installer first.")
        except Exception:
            pass
        print("ERROR: install.json not found. Run the installer first.", file=sys.stderr)
        sys.exit(1)
    try:
        with open(config_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"ERROR: install.json is invalid: {e}", file=sys.stderr)
        sys.exit(1)

_cfg           = _load_install_config()
_install_dir   = Path(_cfg["install_dir"])

SERVER_DIR     = _install_dir / "server"
SAVE_DIR       = _install_dir / "saves"
WORLDS_DIR     = SAVE_DIR / "worlds"
NICKNAMES_FILE = WORLDS_DIR / "nicknames.json"
CONFIG_FILE    = SERVER_DIR / "enshrouded_server.json"
SERVER_BIN     = SERVER_DIR / "enshrouded_server.exe"
LOG_DIR        = SAVE_DIR / "logs"

if sys.platform == "win32":
    GE_PROTON_DIR = None
    WINE64_BIN    = None
    WINE_PREFIX   = None
else:
    GE_PROTON_DIR = Path(_cfg["ge_proton_dir"])
    WINE64_BIN    = GE_PROTON_DIR / "files" / "bin" / "wine64"
    WINE_PREFIX   = SERVER_DIR / "wine_prefix"

NS_PER_MIN      = 60_000_000_000
MACHINE_RE      = re.compile(
    r'm#(\d+)\(\d+\): up \d+ \(\d+\), down \d+ \(\d+\), '
    r'remote \d+ \(\d+\), limit \d+, lost \d+, ping (\d+) ms, (\w+)'
)
STOP_COUNTDOWN_SECS = 5   # visible countdown before sending stop signal
FORCE_KILL_SECS     = 30  # grace period before force-killing if server won't stop
SETTINGS_FILE   = Path(__file__).parent / "manager_settings.json"

# First-run strategy. True = fast: stop the server as soon as its config file
# exists, point the config at an empty world_1, and let the server generate the
# world on the next start (~20-30s first run). False = legacy: wait ~5 min for
# the autosave and migrate the generated world. Flip to False if the fast path
# misbehaves.
FIRST_RUN_FAST = True

# ---------------------------------------------------------------------------
# Theme — dark-navy palette shared with the installer (src/install_tk.py)
# ---------------------------------------------------------------------------
THEME_BG    = "#0f0f1a"   # window background
THEME_HDR   = "#1a1a2e"   # panels, tab bar, borders
THEME_ACC   = "#00d4ff"   # cyan accent (titles, selected tab, focus)
THEME_TXT   = "#e8e8e8"   # primary text
THEME_DIM   = "#888888"   # dim / secondary text
THEME_BTN   = "#1e3a5f"   # default button
THEME_HOVR  = "#2a5080"   # button hover / selection
THEME_FIELD = "#2a2a3f"   # input field background — a few shades above the panels
THEME_LOG   = "#070710"   # log / console background

APP_STYLESHEET = f"""
QWidget {{ background-color: {THEME_BG}; color: {THEME_TXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background-color: {THEME_BG}; }}

QTabWidget::pane {{ border: 1px solid {THEME_HDR}; background: {THEME_BG}; }}
QTabBar::tab {{
    background: {THEME_HDR}; color: {THEME_DIM};
    padding: 8px 16px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{ background: {THEME_BG}; color: {THEME_ACC}; }}
QTabBar::tab:hover {{ color: {THEME_TXT}; }}

QPushButton {{
    background: {THEME_BTN}; color: {THEME_TXT};
    border: none; border-radius: 4px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {THEME_HOVR}; }}
QPushButton:disabled {{ background: {THEME_HDR}; color: #555555; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: {THEME_FIELD}; color: {THEME_TXT};
    border: 1px solid {THEME_HDR}; border-radius: 4px; padding: 4px;
    selection-background-color: {THEME_HOVR};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QTimeEdit:focus {{ border: 1px solid {THEME_ACC}; }}
QComboBox QAbstractItemView {{
    background: {THEME_FIELD}; color: {THEME_TXT};
    selection-background-color: {THEME_HOVR};
}}
QTextEdit {{
    background: {THEME_LOG}; color: {THEME_TXT};
    border: 1px solid {THEME_HDR}; border-radius: 4px;
    selection-background-color: {THEME_HOVR};
}}

QGroupBox {{
    border: 1px solid {THEME_HDR}; border-radius: 6px;
    margin-top: 12px; padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 10px; padding: 0 4px; color: {THEME_ACC};
}}

QListWidget {{
    background: {THEME_FIELD}; color: {THEME_TXT};
    border: 1px solid {THEME_HDR}; border-radius: 4px;
}}
QListWidget::item:selected,
QListWidget::item:selected:!active {{ background: {THEME_HOVR}; color: #ffffff; }}

QCheckBox {{ background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {THEME_HOVR}; border-radius: 3px; background: {THEME_FIELD};
}}
QCheckBox::indicator:checked {{ background: {THEME_ACC}; border: 1px solid {THEME_ACC}; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: {THEME_BG}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {THEME_BTN}; border-radius: 6px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {THEME_HOVR}; }}
QScrollBar:horizontal {{ background: {THEME_BG}; height: 12px; }}
QScrollBar::handle:horizontal {{
    background: {THEME_BTN}; border-radius: 6px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {THEME_HOVR}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

QMenu {{ background: {THEME_HDR}; color: {THEME_TXT}; border: 1px solid {THEME_HOVR}; }}
QMenu::item:selected {{ background: {THEME_HOVR}; }}

QProgressBar {{
    background: {THEME_FIELD}; border: none; border-radius: 4px;
    text-align: center; color: {THEME_TXT};
}}
QProgressBar::chunk {{ background: {THEME_ACC}; border-radius: 4px; }}

QToolTip {{ background: {THEME_HDR}; color: {THEME_TXT}; border: 1px solid {THEME_HOVR}; }}
"""

# ---------------------------------------------------------------------------
# PE subsystem patch — suppress Wine console window for headless server
# ---------------------------------------------------------------------------

# Send Ctrl+C to a console-subsystem child process. taskkill without /F sends
# WM_CLOSE, which a console app with no top-level window ignores — so the server
# would be hard-killed by the force-kill timer before it could flush its save.
# This uses AttachConsole + GenerateConsoleCtrlEvent, the documented way to
# signal a console app from a GUI parent (pythonw.exe).
def _send_ctrl_c_windows(pid: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    import time
    kernel32 = ctypes.windll.kernel32
    CTRL_C_EVENT = 0
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        return False
    try:
        kernel32.SetConsoleCtrlHandler(None, True)
        ok = bool(kernel32.GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0))
        time.sleep(0.1)
    finally:
        kernel32.FreeConsole()
        kernel32.SetConsoleCtrlHandler(None, False)
    return ok


def patch_pe_to_gui(exe: Path) -> bool:
    """Patch a Windows PE executable's subsystem from CONSOLE (3) to WINDOWS (2)."""
    try:
        with open(exe, 'r+b') as f:
            if f.read(2) != b'MZ':
                return False
            f.seek(0x3C)
            pe_offset = struct.unpack('<I', f.read(4))[0]
            f.seek(pe_offset)
            if f.read(4) != b'PE\x00\x00':
                return False
            # Subsystem field: pe_offset + 4 (sig) + 20 (COFF header) + 68 (optional header offset)
            subsystem_off = pe_offset + 4 + 20 + 68
            f.seek(subsystem_off)
            if struct.unpack('<H', f.read(2))[0] == 3:  # IMAGE_SUBSYSTEM_WINDOWS_CUI
                f.seek(subsystem_off)
                f.write(struct.pack('<H', 2))  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Nicknames helpers
# ---------------------------------------------------------------------------

def load_nicknames() -> dict[str, str]:
    try:
        return json.loads(NICKNAMES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_nicknames(nicknames: dict[str, str]):
    NICKNAMES_FILE.write_text(json.dumps(nicknames, indent=2))

def display_name(folder_name: str) -> str:
    return load_nicknames().get(folder_name, folder_name)


# ---------------------------------------------------------------------------
# Manager settings (scheduled restart, etc.)
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_settings(settings: dict):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


# ---------------------------------------------------------------------------
# Migration: move loose save files into worlds/world_1/ on first run
# ---------------------------------------------------------------------------

def migrate_saves_if_needed():
    if WORLDS_DIR.exists():
        return
    WORLDS_DIR.mkdir(parents=True)
    world_dir = WORLDS_DIR / "world_1"
    world_dir.mkdir()
    skip = {"worlds", "logs"}
    for item in SAVE_DIR.iterdir():
        if item.name not in skip and not item.name.startswith("."):
            shutil.move(str(item), str(world_dir / item.name))
    # Give it a friendly nickname
    save_nicknames({"world_1": "World 1"})
    # Point config at the new subfolder
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        data["saveDirectory"] = str(world_dir)
        CONFIG_FILE.write_text(json.dumps(data, indent=4))


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def active_world() -> Path | None:
    if not CONFIG_FILE.exists():
        return None
    data = json.loads(CONFIG_FILE.read_text())
    p = data.get("saveDirectory", "")
    if not p:
        return None
    path = Path(p)
    return path if path.is_absolute() and path.exists() else None

def world_config_path(world_path: Path) -> Path:
    return world_path / "enshrouded_server.json"

def ensure_world_config(world_path: Path):
    """Create a per-world config if one doesn't exist, seeded from CONFIG_FILE."""
    p = world_config_path(world_path)
    if not p.exists() and CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        data["saveDirectory"] = str(world_path)
        p.write_text(json.dumps(data, indent=4))

def set_active_world(path: Path):
    ensure_world_config(path)
    data = json.loads(world_config_path(path).read_text())
    data["saveDirectory"] = str(path)
    CONFIG_FILE.write_text(json.dumps(data, indent=4))

def migrate_world_configs_if_needed():
    """Seed per-world configs for any worlds that predate this feature."""
    if not WORLDS_DIR.exists():
        return
    for world_dir in WORLDS_DIR.iterdir():
        if world_dir.is_dir():
            ensure_world_config(world_dir)


# ---------------------------------------------------------------------------
# First-run migration helpers
# ---------------------------------------------------------------------------

def _needs_first_run_migration() -> bool:
    """True if the server hasn't run yet, or ran but left relative save paths."""
    if not CONFIG_FILE.exists():
        return True
    data = json.loads(CONFIG_FILE.read_text())
    p = data.get("saveDirectory", "")
    return bool(p) and not Path(p).is_absolute()


class FirstRunOverlay(QWidget):
    """Full-window overlay shown during first-run setup. Blocks all tab interaction."""
    skip_requested     = pyqtSignal()
    restart_requested  = pyqtSignal()
    open_log_requested = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        # A plain QWidget ignores a stylesheet background unless this is set —
        # without it the overlay paints nothing and the tabs show through.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"FirstRunOverlay {{ background: {THEME_BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(16)
        layout.addStretch()

        title = QLabel("First-Time Setup")
        title.setStyleSheet(
            f"color: {THEME_ACC}; font-size: 22px; font-weight: bold; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._status = QLabel("Starting server…")
        self._status.setStyleSheet(
            f"color: {THEME_TXT}; font-size: 15px; font-weight: bold; background: transparent;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)

        # Indeterminate busy bar — shown while first-run setup is in progress.
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)          # range 0..0 = animated indeterminate
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setMaximumWidth(320)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background:{THEME_FIELD}; border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{THEME_ACC}; border-radius:4px; }}"
        )

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        # Shown only once setup is fully finished — confirms the user is ready
        # for the manager to restart.
        self._restart_btn = QPushButton("Setup Complete — Restart Manager")
        self._restart_btn.setVisible(False)
        self._restart_btn.setMinimumHeight(36)
        self._restart_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; border-radius:4px; padding:6px 16px; }"
            "QPushButton:hover { background:#2ecc71; }"
        )
        self._restart_btn.clicked.connect(self.restart_requested)

        self._skip_btn = QPushButton("Skip Setup")
        self._skip_btn.setVisible(False)
        self._skip_btn.setMinimumHeight(36)
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ background:{THEME_BTN}; color:{THEME_TXT}; border-radius:4px; padding:6px 12px; }}"
            f"QPushButton:hover {{ background:{THEME_HOVR}; }}"
        )
        self._skip_btn.clicked.connect(self.skip_requested)

        self._log_btn = QPushButton("Open Log in Notepad")
        self._log_btn.setVisible(False)
        self._log_btn.setMinimumHeight(36)
        self._log_btn.setStyleSheet(
            f"QPushButton {{ background:{THEME_BTN}; color:{THEME_TXT}; border-radius:4px; padding:6px 12px; }}"
            f"QPushButton:hover {{ background:{THEME_HOVR}; }}"
        )
        self._log_btn.clicked.connect(self.open_log_requested)

        btn_row.addWidget(self._restart_btn)
        btn_row.addWidget(self._log_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch()

        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self._status)
        layout.addSpacing(16)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(16)
        layout.addLayout(btn_row)
        layout.addStretch()

    def set_status(self, text: str):
        self._status.setText(text)

    def hide_progress(self):
        self._progress.setVisible(False)

    def setup_finished(self, text: str):
        """First-run setup is fully done — stop the busy bar and offer the restart."""
        self._status.setText(text)
        self._progress.setVisible(False)
        self._restart_btn.setVisible(True)

    def show_skip_button(self):
        self._skip_btn.setVisible(True)

    def show_log_button(self):
        self._log_btn.setVisible(True)

    def hide_buttons(self):
        self._restart_btn.setVisible(False)
        self._skip_btn.setVisible(False)
        self._log_btn.setVisible(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())


# ---------------------------------------------------------------------------
# Icon
# ---------------------------------------------------------------------------

def make_icon(running: bool) -> QIcon:
    _ico = Path(__file__).parent / ("running.ico" if running else "manager.ico")
    if _ico.exists():
        return QIcon(str(_ico))
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(40, 180, 60) if running else QColor(160, 40, 40)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    pen = QPen(QColor(255, 255, 255), 5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(20, 18, 20, 46)
    p.drawLine(20, 18, 44, 18)
    p.drawLine(20, 32, 38, 32)
    p.drawLine(20, 46, 44, 46)
    p.end()
    return QIcon(px)


# ---------------------------------------------------------------------------
# Log tab
# ---------------------------------------------------------------------------

class LogWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("monospace", 9))
        layout.addWidget(self._text)
        row = QHBoxLayout()
        self._auto_scroll = QCheckBox("Auto-scroll")
        self._auto_scroll.setChecked(True)
        row.addWidget(self._auto_scroll)
        row.addStretch()
        btn = QPushButton("Clear")
        btn.clicked.connect(self._text.clear)
        row.addWidget(btn)
        layout.addLayout(row)

    def append_plain(self, text: str):
        self._text.append(html.escape(text.rstrip()))
        self._scroll()

    def append_error(self, text: str):
        self._text.append(f'<span style="color:#e74c3c">{html.escape(text.rstrip())}</span>')
        self._scroll()

    def append_info(self, text: str):
        self._text.append(f'<span style="color:#95a5a6"><i>{html.escape(text.rstrip())}</i></span>')
        self._scroll()

    def _scroll(self):
        if self._auto_scroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# Worlds tab
# ---------------------------------------------------------------------------

class WorldsWidget(QWidget):
    world_switched = pyqtSignal()

    def __init__(self, is_running_fn, get_snapshot_fn=None):
        super().__init__()
        self._is_running = is_running_fn
        self._get_snapshot = get_snapshot_fn or (lambda: None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._switch)
        layout.addWidget(self._list)

        self._active_lbl = QLabel("")
        self._active_lbl.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._active_lbl)

        btn_row = QHBoxLayout()
        self._switch_btn   = QPushButton("Switch to Selected")
        self._nickname_btn = QPushButton("Set Nickname")
        self._import_btn   = QPushButton("Import Save…")
        self._delete_btn   = QPushButton("Delete World")
        self._delete_btn.setStyleSheet(
            "QPushButton { background:#c0392b; color:white; border-radius:4px; }"
            "QPushButton:hover { background:#e74c3c; }"
            "QPushButton:disabled { background:#555; color:#999; }"
        )
        for btn in (self._switch_btn, self._nickname_btn,
                    self._import_btn, self._delete_btn):
            btn.setMinimumHeight(38)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._switch_btn.clicked.connect(self._switch)
        self._nickname_btn.clicked.connect(self._set_nickname)
        self._import_btn.clicked.connect(self._import_world)
        self._delete_btn.clicked.connect(self._delete_world)

        self.refresh()

    def refresh(self):
        self._list.clear()
        if not WORLDS_DIR.exists():
            return

        current  = active_world()
        nicknames = load_nicknames()
        worlds = sorted(
            [d for d in WORLDS_DIR.iterdir() if d.is_dir()],
            key=lambda d: nicknames.get(d.name, d.name).lower(),
        )

        snapshot = self._get_snapshot()
        for world in worlds:
            is_active   = bool(current and world.resolve() == current.resolve())
            is_snapshot = bool(snapshot and world.name == snapshot)
            nick = nicknames.get(world.name, world.name)
            snap_tag = "  [snapshot]" if is_snapshot else ""
            label = f"{'▶  ' if is_active else '    '}{nick}  ({world.name}){snap_tag}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, world)
            if is_active:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            if is_snapshot:
                item.setForeground(QColor("#e67e22"))
            self._list.addItem(item)

        if current:
            nick = nicknames.get(current.name, current.name)
            self._active_lbl.setText(f"Active: {nick}  —  {current}")
        else:
            self._active_lbl.setText("No active world set")

    def _selected_world(self) -> Path | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _switch(self):
        world = self._selected_world()
        if not world:
            return
        snapshot = self._get_snapshot()
        if snapshot and world.name == snapshot:
            QMessageBox.warning(self, "Snapshot World",
                "This world is set as the resource server snapshot and cannot be made active.")
            return
        current = active_world()
        if current and world.resolve() == current.resolve():
            return
        if self._is_running():
            QMessageBox.warning(self, "Server Running",
                                "Stop the server before switching worlds.")
            return
        set_active_world(world)
        self.refresh()
        self.world_switched.emit()

    def _delete_world(self):
        world = self._selected_world()
        if not world:
            return
        if self._is_running():
            QMessageBox.warning(self, "Server Running",
                                "Stop the server before deleting a world.")
            return
        current = active_world()
        if current and world.resolve() == current.resolve():
            QMessageBox.warning(self, "Active World",
                                "Cannot delete the active world. Switch to another world first.")
            return
        nick = load_nicknames().get(world.name, world.name)
        reply = QMessageBox.question(
            self, "Delete World",
            f"Permanently delete '{nick}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(str(world))
        nicknames = load_nicknames()
        nicknames.pop(world.name, None)
        save_nicknames(nicknames)
        self.refresh()

    def _import_world(self):
        # Start browser in Steam cloud save dir if it exists
        if sys.platform == "win32":
            steam_remote = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam" / "userdata"
        else:
            steam_remote = Path.home() / ".local/share/Steam/userdata"
        start_dir = str(Path.home())
        for user_dir in (steam_remote.iterdir() if steam_remote.exists() else []):
            remote = user_dir / "1203620" / "remote"
            if remote.exists():
                start_dir = str(remote)
                break

        path, _ = QFileDialog.getOpenFileName(
            self, "Select a save file to import", start_dir, "All files (*)")
        if not path:
            return
        path = Path(path)

        # Derive the hash prefix by stripping -N or -index suffixes
        name = path.name
        if name.endswith("-index"):
            hash_name = name[:-len("-index")]
        elif "_info" in name:
            QMessageBox.warning(self, "Invalid File",
                "Please select a save file, not a Steam info file.")
            return
        else:
            # Strip trailing -N (single digit)
            import re as _re
            hash_name = _re.sub(r"-\d+$", "", name)

        src_dir = path.parent
        index_file = src_dir / f"{hash_name}-index"
        if not index_file.exists():
            QMessageBox.warning(self, "Index Not Found",
                f"Could not find {hash_name}-index alongside the selected file.")
            return

        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(self, "Invalid Index File",
                f"Could not read the save index file:\n{index_file.name}\n\n{e}")
            return

        nick, ok = QInputDialog.getText(self, "Import World", "World nickname:")
        if not ok or not nick.strip():
            return
        nick = nick.strip()

        folder_name = nick.lower().replace(" ", "_")
        base = folder_name
        counter = 2
        while (WORLDS_DIR / folder_name).exists():
            folder_name = f"{base}_{counter}"
            counter += 1
        world_dir = WORLDS_DIR / folder_name
        world_dir.mkdir(parents=True)

        # The dedicated server always uses its own fixed save hash (e.g. 3ad85aea)
        # regardless of the source file's hash. Detect it from an existing world.
        server_hash = None

        def _find_hash_in(directory: Path) -> str | None:
            try:
                for f in directory.iterdir():
                    if f.name.endswith("-index") and f.is_file():
                        return f.name[:-len("-index")]
            except OSError:
                pass
            return None

        # Pass 1: check CONFIG_FILE's saveDirectory (resolve relative paths against SERVER_DIR).
        if CONFIG_FILE.exists():
            try:
                _cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8", errors="replace"))
                _sd_raw = _cfg.get("saveDirectory", "")
                if _sd_raw:
                    _sd = Path(_sd_raw)
                    if not _sd.is_absolute():
                        _sd = (SERVER_DIR / _sd).resolve()
                    for _search in [_sd, _sd / "savegame"]:
                        server_hash = _find_hash_in(_search)
                        if server_hash:
                            break
            except (json.JSONDecodeError, OSError):
                pass

        # Pass 2: recursively scan all managed world dirs.
        if not server_hash and WORLDS_DIR.exists():
            try:
                for wd in WORLDS_DIR.iterdir():
                    if wd == world_dir or not wd.is_dir():
                        continue
                    for f in wd.rglob("*-index"):
                        if f.is_file():
                            server_hash = f.name[:-len("-index")]
                            break
                    if server_hash:
                        break
            except OSError:
                pass

        # Pass 3: scan SERVER_DIR subdirs (catches pre-migration saves or alternate paths).
        if not server_hash:
            try:
                for sub in SERVER_DIR.iterdir():
                    if not sub.is_dir():
                        continue
                    server_hash = _find_hash_in(sub)
                    if server_hash:
                        break
            except OSError:
                pass

        if not server_hash:
            QMessageBox.warning(self, "Cannot Import",
                "Could not determine the server's save hash.\n\n"
                "The server must have run at least once so it can create its save files.\n"
                "Start the server, let it run for 30 seconds, then retry the import.")
            shutil.rmtree(str(world_dir), ignore_errors=True)
            return

        latest = index_data.get("latest", 0)
        latest_file = src_dir / (hash_name if latest == 0 else f"{hash_name}-{latest}")
        if not latest_file.exists():
            QMessageBox.warning(self, "Save Not Found",
                f"Latest save slot not found: {latest_file.name}")
            shutil.rmtree(str(world_dir))
            return

        # Copy the latest slot as the server's base hash file (no slot suffix).
        # Write an index with latest=0 so the server loads that base file.
        import time as _time
        dest_save = world_dir / server_hash
        shutil.copy2(str(latest_file), str(dest_save))
        new_index = {"latest": 0, "time": int(_time.time()), "deleted": False}
        (world_dir / f"{server_hash}-index").write_text(
            json.dumps(new_index, indent="\t"))

        ensure_world_config(world_dir)
        nicknames = load_nicknames()
        nicknames[folder_name] = nick
        save_nicknames(nicknames)
        self.refresh()

        QMessageBox.information(self, "Import Complete",
            f"'{nick}' imported to:\n{world_dir}\n\n"
            f"Source: {latest_file.name}  (slot {latest})\n"
            f"Saved as: {server_hash}  (index latest=0)")

    def _set_nickname(self):
        world = self._selected_world()
        if not world:
            return
        nicknames = load_nicknames()
        current_nick = nicknames.get(world.name, world.name)
        new_nick, ok = QInputDialog.getText(
            self, "Set Nickname", "Nickname for this world:", text=current_nick)
        if not ok or not new_nick.strip():
            return
        nicknames[world.name] = new_nick.strip()
        save_nicknames(nicknames)
        self.refresh()
        self.world_switched.emit()


# ---------------------------------------------------------------------------
# User group editor (used inside Config tab Access section)
# ---------------------------------------------------------------------------

class UserGroupEditor(QGroupBox):
    remove_requested = pyqtSignal(object)

    def __init__(self, group: dict):
        super().__init__()
        self._original = group
        outer = QVBoxLayout(self)

        # Header row: name + remove button
        header = QHBoxLayout()
        self._name_edit = QLineEdit(group.get("name", "Group"))
        self._name_edit.setPlaceholderText("Group name")
        self._name_edit.textChanged.connect(lambda t: self.setTitle(t or "Group"))
        self.setTitle(group.get("name", "Group"))
        remove_btn = QPushButton("Remove")
        remove_btn.setFixedWidth(70)
        remove_btn.setStyleSheet("QPushButton { background:#c0392b; color:white; border-radius:4px; }"
                                 "QPushButton:hover { background:#e74c3c; }")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(QLabel("Name:"))
        header.addWidget(self._name_edit)
        header.addWidget(remove_btn)
        outer.addLayout(header)

        f = QFormLayout()
        self._password = QLineEdit(group.get("password", ""))
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow("Password:", self._password)

        self._kick_ban    = QCheckBox(); self._kick_ban.setChecked(group.get("canKickBan", False))
        self._inventories = QCheckBox(); self._inventories.setChecked(group.get("canAccessInventories", False))
        self._edit_world  = QCheckBox(); self._edit_world.setChecked(group.get("canEditWorld", False))
        self._edit_base   = QCheckBox(); self._edit_base.setChecked(group.get("canEditBase", False))
        self._extend_base = QCheckBox(); self._extend_base.setChecked(group.get("canExtendBase", False))
        f.addRow("Can Kick/Ban:",       self._kick_ban)
        f.addRow("Access Inventories:", self._inventories)
        f.addRow("Edit World:",         self._edit_world)
        f.addRow("Edit Base:",          self._edit_base)
        f.addRow("Extend Base:",        self._extend_base)

        self._slots = QSpinBox()
        self._slots.setRange(0, 16)
        self._slots.setValue(group.get("reservedSlots", 0))
        f.addRow("Reserved Slots:", self._slots)
        outer.addLayout(f)

    def get_data(self) -> dict:
        d = dict(self._original)
        d["name"]                 = self._name_edit.text()
        d["password"]             = self._password.text()
        d["canKickBan"]           = self._kick_ban.isChecked()
        d["canAccessInventories"] = self._inventories.isChecked()
        d["canEditWorld"]         = self._edit_world.isChecked()
        d["canEditBase"]          = self._edit_base.isChecked()
        d["canExtendBase"]        = self._extend_base.isChecked()
        d["reservedSlots"]        = self._slots.value()
        return d


# ---------------------------------------------------------------------------
# Config tab
# ---------------------------------------------------------------------------

class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._fields: dict[str, tuple] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        outer.addWidget(scroll)
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(8)

        g = QGroupBox("Server")
        f = QFormLayout(g)
        self._add_str(f,   "name",       "Server Name")
        self._add_str(f,   "ip",         "Bind IP")
        self._add_int(f,   "queryPort",  "Query Port", 1024, 65535)
        self._add_int(f,   "slotCount",  "Max Players", 1, 16)
        layout.addWidget(g)

        g = QGroupBox("Chat")
        f = QFormLayout(g)
        self._add_bool(f,  "enableVoiceChat", "Voice Chat")
        self._add_bool(f,  "enableTextChat",  "Text Chat")
        self._add_combo(f, "voiceChatMode",   "Voice Mode", ["Proximity", "Global"])
        layout.addWidget(g)

        g = QGroupBox("Game Preset")
        f = QFormLayout(g)
        self._add_combo(f, "gameSettingsPreset", "Preset",
                        ["Default", "Relaxed", "Hard", "Survival", "Custom"])
        layout.addWidget(g)

        g = QGroupBox("Player")
        f = QFormLayout(g)
        for k, lbl in [
            ("playerHealthFactor",    "Health"),
            ("playerManaFactor",      "Mana"),
            ("playerStaminaFactor",   "Stamina"),
            ("playerBodyHeatFactor",  "Body Heat"),
            ("playerDivingTimeFactor","Diving Time"),
            ("shroudTimeFactor",      "Shroud Time"),
            ("foodBuffDurationFactor","Food Buff Duration"),
        ]:
            self._add_float(f, k, lbl, 0.1, 10.0, gs=True)
        self._add_float(f, "_hungerMinutes", "Hunger → Starving (min)", 1.0, 600.0)
        self._add_bool(f, "enableDurability",     "Durability",     gs=True)
        self._add_bool(f, "enableStarvingDebuff", "Starving Debuff", gs=True)
        layout.addWidget(g)

        g = QGroupBox("World")
        f = QFormLayout(g)
        self._add_combo(f, "weatherFrequency", "Weather",  ["Normal", "Rare", "Never"],  gs=True)
        self._add_combo(f, "fishingDifficulty","Fishing",  ["Easy", "Normal", "Hard"],    gs=True)
        self._add_float(f, "plantGrowthSpeedFactor",        "Plant Growth",   0.1, 10.0, gs=True)
        self._add_float(f, "miningDamageFactor",            "Mining Damage",  0.1, 10.0, gs=True)
        self._add_float(f, "resourceDropStackAmountFactor", "Resource Drops", 0.1, 10.0, gs=True)
        self._add_float(f, "factoryProductionSpeedFactor",  "Factory Speed",  0.1, 10.0, gs=True)
        self._add_combo(f, "curseModifier", "Curse", ["Normal", "Hard", "Veryhard"],       gs=True)
        layout.addWidget(g)

        g = QGroupBox("Day / Night Cycle")
        f = QFormLayout(g)
        self._add_float(f, "_dayMinutes",   "Day Length (min)",   1.0, 300.0)
        self._add_float(f, "_nightMinutes", "Night Length (min)", 1.0, 300.0)
        layout.addWidget(g)

        g = QGroupBox("Combat")
        f = QFormLayout(g)
        for k, lbl in [
            ("enemyDamageFactor",          "Enemy Damage"),
            ("enemyHealthFactor",          "Enemy Health"),
            ("enemyStaminaFactor",         "Enemy Stamina"),
            ("enemyPerceptionRangeFactor", "Enemy Perception"),
            ("bossDamageFactor",           "Boss Damage"),
            ("bossHealthFactor",           "Boss Health"),
            ("threatBonus",                "Threat Bonus"),
        ]:
            self._add_float(f, k, lbl, 0.1, 10.0, gs=True)
        self._add_bool(f, "pacifyAllEnemies", "Pacify All Enemies", gs=True)
        layout.addWidget(g)

        g = QGroupBox("Experience")
        f = QFormLayout(g)
        for k, lbl in [
            ("experienceCombatFactor",            "Combat XP"),
            ("experienceMiningFactor",            "Mining XP"),
            ("experienceExplorationQuestsFactor", "Exploration XP"),
            ("perkUpgradeRecyclingFactor",        "Perk Recycle Rate"),
            ("perkCostFactor",                    "Perk Cost"),
        ]:
            self._add_float(f, k, lbl, 0.0, 10.0, gs=True)
        layout.addWidget(g)

        g = QGroupBox("Misc")
        f = QFormLayout(g)
        self._add_combo(f, "tombstoneMode", "Tombstone",
                        ["AddBackpackMaterials", "NoTombstone", "Backpack"], gs=True)
        self._add_combo(f, "tamingStartleRepercussion", "Taming Startle",
                        ["LoseSomeProgress", "LoseAllProgress", "Nothing"], gs=True)
        self._add_bool(f,  "enableGliderTurbulences", "Glider Turbulences",  gs=True)
        self._add_combo(f, "randomSpawnerAmount", "Spawner Amount", ["Normal", "Few", "Many"], gs=True)
        self._add_combo(f, "aggroPoolAmount",     "Aggro Pool",     ["Normal", "Few", "Many"], gs=True)
        layout.addWidget(g)

        g = QGroupBox("Access — User Groups")
        g_layout = QVBoxLayout(g)
        self._groups_container = QWidget()
        self._groups_layout = QVBoxLayout(self._groups_container)
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(8)
        g_layout.addWidget(self._groups_container)
        add_btn = QPushButton("+ Add Group")
        add_btn.clicked.connect(lambda: self._add_group())
        g_layout.addWidget(add_btn)
        layout.addWidget(g)
        self._group_editors: list[UserGroupEditor] = []

        self._save_btn = QPushButton("Save Configuration")
        self._save_btn.setMinimumHeight(40)
        self._save_btn.clicked.connect(self.save_config)
        outer.addWidget(self._save_btn)

    def _add_group(self, group: dict | None = None):
        if group is None:
            group = {"name": "New Group", "password": "", "canKickBan": False,
                     "canAccessInventories": False, "canEditWorld": False,
                     "canEditBase": False, "canExtendBase": False, "reservedSlots": 0}
        editor = UserGroupEditor(group)
        editor.remove_requested.connect(self._remove_group)
        self._groups_layout.addWidget(editor)
        self._group_editors.append(editor)

    def _remove_group(self, editor: UserGroupEditor):
        self._groups_layout.removeWidget(editor)
        self._group_editors.remove(editor)
        editor.deleteLater()

    def _add_str(self, form, key, label, gs=False):
        w = QLineEdit()
        self._fields[key] = (w, "str", gs)
        form.addRow(f"{label}:", w)

    def _add_int(self, form, key, label, mn, mx, gs=False):
        w = QSpinBox()
        w.setRange(mn, mx)
        self._fields[key] = (w, "int", gs)
        form.addRow(f"{label}:", w)

    def _add_float(self, form, key, label, mn, mx, gs=False):
        w = QDoubleSpinBox()
        w.setRange(mn, mx)
        w.setSingleStep(0.1)
        w.setDecimals(2)
        self._fields[key] = (w, "float", gs)
        form.addRow(f"{label}:", w)

    def _add_bool(self, form, key, label, gs=False):
        w = QCheckBox()
        self._fields[key] = (w, "bool", gs)
        form.addRow(f"{label}:", w)

    def _add_combo(self, form, key, label, options, gs=False):
        w = QComboBox()
        w.addItems(options)
        self._fields[key] = (w, "combo", gs)
        form.addRow(f"{label}:", w)

    def load_config(self, data: dict):
        gs = data.get("gameSettings", {})
        for key, (widget, typ, is_gs) in self._fields.items():
            if key == "_dayMinutes":
                val = gs.get("dayTimeDuration", 1800000000000) / NS_PER_MIN
            elif key == "_nightMinutes":
                val = gs.get("nightTimeDuration", 720000000000) / NS_PER_MIN
            elif key == "_hungerMinutes":
                val = gs.get("fromHungerToStarving", 600000000000) / NS_PER_MIN
            else:
                val = gs.get(key) if is_gs else data.get(key)
            if val is None:
                continue
            if typ == "str":
                widget.setText(str(val))
            elif typ == "int":
                widget.setValue(int(val))
            elif typ == "float":
                widget.setValue(float(val))
            elif typ == "bool":
                widget.setChecked(bool(val))
            elif typ == "combo":
                idx = widget.findText(str(val), Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
        while self._groups_layout.count():
            item = self._groups_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._group_editors.clear()
        for group in data.get("userGroups", []):
            self._add_group(group)

    def save_config(self):
        if not CONFIG_FILE.exists():
            QMessageBox.warning(self, "Error", f"Config not found:\n{CONFIG_FILE}")
            return
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        gs = data.setdefault("gameSettings", {})
        for key, (widget, typ, is_gs) in self._fields.items():
            if typ == "str":     val = widget.text()
            elif typ == "int":   val = widget.value()
            elif typ == "float": val = widget.value()
            elif typ == "bool":  val = widget.isChecked()
            elif typ == "combo": val = widget.currentText()
            if key == "_dayMinutes":
                gs["dayTimeDuration"] = int(val * NS_PER_MIN)
            elif key == "_nightMinutes":
                gs["nightTimeDuration"] = int(val * NS_PER_MIN)
            elif key == "_hungerMinutes":
                gs["fromHungerToStarving"] = int(val * NS_PER_MIN)
            elif is_gs:
                gs[key] = val
            else:
                data[key] = val
        data["userGroups"] = [e.get_data() for e in self._group_editors]
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
        world = active_world()
        if world:
            with open(world_config_path(world), "w") as f:
                json.dump(data, f, indent=4)
        self._save_btn.setText("Saved!")
        self._save_btn.setEnabled(False)
        QTimer.singleShot(2000, lambda: (
            self._save_btn.setText("Save Configuration"),
            self._save_btn.setEnabled(True),
        ))


# ---------------------------------------------------------------------------
# Resource Server tab
# ---------------------------------------------------------------------------

class ResourceServerTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        grp = QGroupBox("Resource Server Mode")
        f = QFormLayout(grp)

        self._enabled_cb = QCheckBox("Enable resource server mode")
        f.addRow(self._enabled_cb)

        self._snapshot_combo = QComboBox()
        f.addRow("Snapshot World:", self._snapshot_combo)

        self._password_edit = QLineEdit()
        self._password_edit.setPlaceholderText("No password (open access)")
        f.addRow("Resource Group Password:", self._password_edit)

        interval_w = QWidget()
        int_row = QHBoxLayout(interval_w)
        int_row.setContentsMargins(0, 0, 0, 0)
        self._hours_spin = QSpinBox()
        self._hours_spin.setRange(0, 168)
        self._hours_spin.setSuffix(" h")
        self._mins_spin = QSpinBox()
        self._mins_spin.setRange(0, 59)
        self._mins_spin.setSuffix(" m")
        int_row.addWidget(self._hours_spin)
        int_row.addWidget(self._mins_spin)
        int_row.addStretch()
        f.addRow("Reset Interval:", interval_w)

        self._next_reset_lbl = QLabel("Disabled")
        self._next_reset_lbl.setStyleSheet("color: gray; font-style: italic;")
        f.addRow("Next Reset:", self._next_reset_lbl)

        layout.addWidget(grp)

        self.restart_snapshot_btn = QPushButton("↺  Restart with Snapshot Now")
        self.restart_snapshot_btn.setMinimumHeight(44)
        self.restart_snapshot_btn.setStyleSheet(
            "QPushButton { background:#8e44ad; color:white; font-size:13px; "
            "font-weight:bold; border-radius:6px; }"
            "QPushButton:disabled { background:#555; color:#999; }"
        )
        self.restart_snapshot_btn.setEnabled(False)
        layout.addWidget(self.restart_snapshot_btn)
        layout.addStretch()

    def refresh_worlds(self):
        current = self._snapshot_combo.currentData()
        self._snapshot_combo.clear()
        self._snapshot_combo.addItem("None", None)
        if not WORLDS_DIR.exists():
            return
        nicknames = load_nicknames()
        worlds = sorted(
            [d for d in WORLDS_DIR.iterdir() if d.is_dir()],
            key=lambda d: nicknames.get(d.name, d.name).lower(),
        )
        for world in worlds:
            self._snapshot_combo.addItem(nicknames.get(world.name, world.name), world.name)
        if current:
            idx = self._snapshot_combo.findData(current)
            if idx >= 0:
                self._snapshot_combo.setCurrentIndex(idx)

    def snapshot_folder(self) -> str | None:
        return self._snapshot_combo.currentData() or None

    def interval_minutes(self) -> int:
        return self._hours_spin.value() * 60 + self._mins_spin.value()

    def is_enabled(self) -> bool:
        return self._enabled_cb.isChecked()


# ---------------------------------------------------------------------------
# Server tab
# ---------------------------------------------------------------------------

class ServerTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)

        g = QGroupBox("Status")
        row = QHBoxLayout(g)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color: #c0392b; font-size: 28px;")
        self._status_lbl = QLabel("Stopped")
        self._status_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
        self._uptime_lbl = QLabel("")
        self._uptime_lbl.setStyleSheet("color: gray;")
        row.addWidget(self._dot)
        row.addWidget(self._status_lbl)
        row.addStretch()
        row.addWidget(self._uptime_lbl)
        layout.addWidget(g)

        g = QGroupBox("Controls")
        row = QHBoxLayout(g)
        self.start_btn   = QPushButton("▶  Start")
        self.stop_btn    = QPushButton("■  Stop")
        self.restart_btn = QPushButton("↺  Restart")
        for btn, color in [
            (self.start_btn,   "#27ae60"),
            (self.stop_btn,    "#c0392b"),
            (self.restart_btn, "#e67e22"),
        ]:
            btn.setMinimumHeight(48)
            btn.setStyleSheet(
                f"QPushButton {{ background:{color}; color:white; font-size:14px; "
                f"font-weight:bold; border-radius:6px; }}"
                f"QPushButton:disabled {{ background:#555; color:#999; }}"
            )
            row.addWidget(btn)
        self.stop_btn.setEnabled(False)
        self.restart_btn.setEnabled(False)
        layout.addWidget(g)

        g = QGroupBox("Server Info")
        f = QFormLayout(g)
        self._name_lbl         = QLabel("—")
        self._port_lbl         = QLabel("—")
        self._slots_lbl        = QLabel("—")
        self._world_lbl        = QLabel("—")
        self._last_restart_lbl = QLabel("—")
        f.addRow("Name:",          self._name_lbl)
        f.addRow("Port:",          self._port_lbl)
        f.addRow("Slots:",         self._slots_lbl)
        f.addRow("Active World:",  self._world_lbl)
        f.addRow("Last Restart:",  self._last_restart_lbl)
        layout.addWidget(g)

        g = QGroupBox("Session")
        f = QFormLayout(g)
        self._players_lbl = QLabel("—")
        self._ping_lbl    = QLabel("—")
        self._net_lbl     = QLabel("—")
        f.addRow("Players:",    self._players_lbl)
        f.addRow("Ping:",       self._ping_lbl)
        f.addRow("Net Status:", self._net_lbl)
        layout.addWidget(g)

        g = QGroupBox("Scheduled Restart")
        f = QFormLayout(g)
        self._sched_enable = QCheckBox("Enable daily restart")
        self._sched_time   = QTimeEdit()
        self._sched_time.setDisplayFormat("hh:mm AP")
        self._sched_time.setTime(QTime(4, 0))
        self._sched_next   = QLabel("Disabled")
        self._sched_next.setStyleSheet("color: gray; font-style: italic;")
        f.addRow(self._sched_enable)
        f.addRow("Restart at:",   self._sched_time)
        f.addRow("Next restart:", self._sched_next)
        layout.addWidget(g)

        self._start_time: datetime | None = None
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(1000)

    def set_running(self, running: bool):
        if running:
            self._dot.setStyleSheet("color: #27ae60; font-size: 28px;")
            self._status_lbl.setText("Running")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.restart_btn.setEnabled(True)
            if self._start_time is None:
                self._start_time = datetime.now()
        else:
            self._dot.setStyleSheet("color: #c0392b; font-size: 28px;")
            self._status_lbl.setText("Stopped")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.restart_btn.setEnabled(False)
            self._start_time = None
            self._uptime_lbl.setText("")
            self._players_lbl.setText("—")
            self._ping_lbl.setText("—")
            self._net_lbl.setText("—")

    def update_info(self, data: dict):
        self._name_lbl.setText(data.get("name", "—"))
        self._port_lbl.setText(str(data.get("queryPort", "—")))
        self._slots_lbl.setText(str(data.get("slotCount", "—")))
        save = data.get("saveDirectory", "")
        if save:
            folder = Path(save).name
            nick = load_nicknames().get(folder, folder)
            self._world_lbl.setText(nick)
        else:
            self._world_lbl.setText("—")

    def set_session_info(self, players: int, ping: int, status: str):
        self._players_lbl.setText(str(players))
        self._ping_lbl.setText(f"{ping} ms")
        self._net_lbl.setText(status)

    def _tick(self):
        if self._start_time:
            delta = datetime.now() - self._start_time
            h, r = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(r, 60)
            self._uptime_lbl.setText(f"Uptime: {h:02d}:{m:02d}:{s:02d}")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enshrouded Server Manager")
        _win_icon = Path(__file__).parent / "manager.ico"
        if _win_icon.exists():
            self.setWindowIcon(QIcon(str(_win_icon)))
        self.resize(860, 660)

        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.started.connect(self._on_server_started)
        self._process.finished.connect(self._on_server_stopped)

        self._log_tail_pos = 0
        self._active_log_path = LOG_DIR / "enshrouded_server.log"
        self._log_tail_timer = QTimer(self)
        self._log_tail_timer.setInterval(500)
        self._log_tail_timer.timeout.connect(self._tail_server_log)

        self._force_kill_timer = QTimer(self)
        self._force_kill_timer.setSingleShot(True)
        self._force_kill_timer.timeout.connect(self._force_kill)

        self._migration_pending = False
        self._migration_timer = QTimer(self)
        self._migration_timer.setInterval(10_000)
        self._migration_timer.timeout.connect(self._check_first_run_migration)

        # Fast first-run: short poll for the server's config file (see FIRST_RUN_FAST).
        self._fast_first_run_timer = QTimer(self)
        self._fast_first_run_timer.setInterval(1_500)
        self._fast_first_run_timer.timeout.connect(self._check_fast_first_run)

        self._overlay: FirstRunOverlay | None = None

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self._server_tab = ServerTab()
        self._server_tab.start_btn.clicked.connect(self.start_server)
        self._server_tab.stop_btn.clicked.connect(self.stop_with_countdown)
        self._server_tab.restart_btn.clicked.connect(self.restart_server)
        tabs.addTab(self._server_tab, "Server")

        self._log = LogWidget()
        tabs.addTab(self._log, "Logs")

        self._resource_tab = ResourceServerTab()
        tabs.addTab(self._resource_tab, "Resource Server")

        self._worlds = WorldsWidget(self._is_running,
                                    lambda: self._resource_tab.snapshot_folder())
        self._worlds.world_switched.connect(self._reload_config)
        tabs.addTab(self._worlds, "Worlds")

        self._config = ConfigWidget()
        tabs.addTab(self._config, "Configuration")

        self._reload_config()

        self._resource_restore_pending = False
        self._resource_next_reset: datetime | None = None

        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(30_000)
        self._resource_timer.timeout.connect(self._check_resource_restart)
        self._resource_timer.start()

        self._resource_label_timer = QTimer(self)
        self._resource_label_timer.setInterval(1_000)
        self._resource_label_timer.timeout.connect(self._update_resource_next_label)
        self._resource_label_timer.start()

        self._resource_tab._enabled_cb.toggled.connect(self._on_resource_mode_changed)
        self._resource_tab._snapshot_combo.currentIndexChanged.connect(self._save_resource_settings)
        self._resource_tab._snapshot_combo.currentIndexChanged.connect(self._worlds.refresh)
        self._resource_tab._hours_spin.valueChanged.connect(self._save_resource_settings)
        self._resource_tab._mins_spin.valueChanged.connect(self._save_resource_settings)
        self._resource_tab._password_edit.textChanged.connect(self._save_resource_settings)
        self._resource_tab.restart_snapshot_btn.clicked.connect(self._manual_resource_restart)
        self._worlds.world_switched.connect(self._resource_tab.refresh_worlds)
        self._resource_tab.refresh_worlds()

        self._scheduled_restart_date = None
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(30_000)
        self._schedule_timer.timeout.connect(self._check_scheduled_restart)
        self._schedule_timer.start()

        self._server_tab._sched_enable.toggled.connect(self._save_schedule)
        self._server_tab._sched_time.timeChanged.connect(self._save_schedule)
        self._load_schedule()
        self._load_resource_settings()

        # Overlay must be created last so it stacks above all other widgets.
        if _needs_first_run_migration():
            self._overlay = FirstRunOverlay(self)
            self._overlay.skip_requested.connect(self._dismiss_overlay)
            self._overlay.restart_requested.connect(self._restart_manager)
            self._overlay.open_log_requested.connect(self._open_first_run_log)
            self._overlay.setGeometry(0, 0, self.width(), self.height())
            self._overlay.show()
            self._overlay.raise_()

    def _reload_config(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            self._server_tab.update_info(data)
            self._config.load_config(data)

    def _is_running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def start_server(self):
        if not SERVER_BIN.exists():
            QMessageBox.critical(self, "Error", f"Server binary not found:\n{SERVER_BIN}")
            return
        if sys.platform != "win32" and not WINE64_BIN.exists():
            QMessageBox.critical(self, "Error", f"Wine not found:\n{WINE64_BIN}")
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Kill any orphaned server processes from prior sessions.
        if sys.platform == "win32":
            # stdin=DEVNULL: pythonw.exe has a NULL stdin handle and capture_output
            # would otherwise trip _winapi.DuplicateHandle with WinError 6.
            subprocess.run(["taskkill", "/F", "/IM", "enshrouded_server.exe"],
                           capture_output=True, stdin=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-KILL", "-f", "enshrouded_server.exe"],
                           capture_output=True)
            # Kill only our prefix's wineserver (not system-wide).
            wineserver_bin = GE_PROTON_DIR / "files" / "bin" / "wineserver"
            if wineserver_bin.exists():
                subprocess.run(
                    [str(wineserver_bin), "-k9"],
                    env={**os.environ, "WINEPREFIX": str(WINE_PREFIX)},
                    capture_output=True, timeout=5,
                )
        self._log.append_info(f"Starting server — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        # Wait for ports to clear without blocking the event loop, then launch.
        self._port_wait_attempts = 0
        self._port_wait_timer = QTimer(self)
        self._port_wait_timer.setInterval(1000)
        self._port_wait_timer.timeout.connect(self._wait_for_port_then_start)
        self._port_wait_timer.start()

    def _wait_for_port_then_start(self):
        import socket
        ports_clear = True
        for port in (15636, 15637):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                try:
                    s.bind(("", port))
                except OSError:
                    ports_clear = False
                    break
        self._port_wait_attempts += 1
        if ports_clear or self._port_wait_attempts >= 8:
            self._port_wait_timer.stop()
            self._port_wait_timer.deleteLater()
            self._do_start_server()

    def _do_start_server(self):
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SteamAppId", "1203620")
        env.insert("SteamGameId", "1203620")
        if sys.platform != "win32":
            env.insert("HOME", os.environ.get("HOME", str(Path.home())))
            env.insert("WINEPREFIX", str(WINE_PREFIX))
            wine_lib = str(GE_PROTON_DIR / "files" / "lib")
            existing_ld = env.value("LD_LIBRARY_PATH", "")
            env.insert("LD_LIBRARY_PATH", f"{wine_lib}:{existing_ld}" if existing_ld else wine_lib)
            env.insert("WINEDLLOVERRIDES", "wineconsole=d")
            env.insert("WINEDEBUG", "-all")
            env.insert("XDG_RUNTIME_DIR", os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        self._process.setProcessEnvironment(env)
        self._process.setWorkingDirectory(str(SERVER_DIR))
        self._apply_resource_group()
        if sys.platform == "win32":
            self._process.start(str(SERVER_BIN), [])
        else:
            self._process.start(str(WINE64_BIN), [str(SERVER_BIN)])

    def stop_server(self):
        self._log.append_info("Stopping server…")
        pid = self._process.processId()
        if pid > 0:
            if sys.platform == "win32":
                # The server is a console-subsystem app with no top-level window,
                # so taskkill /PID (WM_CLOSE) is silently ignored. Send Ctrl+C
                # via the console API so the server can save before exiting.
                if not _send_ctrl_c_windows(pid):
                    self._log.append_info(
                        "Could not attach to server console — falling back to taskkill.")
                    subprocess.run(["taskkill", "/PID", str(pid)],
                                   capture_output=True, stdin=subprocess.DEVNULL,
                                   check=False)
            else:
                import signal as _signal
                try:
                    os.kill(pid, _signal.SIGINT)
                except ProcessLookupError:
                    pass
        self._force_kill_timer.start(FORCE_KILL_SECS * 1000)

    def _force_kill(self):
        if self._is_running():
            self._log.append_info("Server did not exit in time — terminating.")
            self._process.kill()

    def stop_with_countdown(self):
        self._stop_countdown_n = STOP_COUNTDOWN_SECS
        self._stop_tick()

    def restart_server(self):
        self._log.append_info("Restarting server…")
        self._process.finished.connect(
            self._restart_after_stop, Qt.ConnectionType.SingleShotConnection)
        self._stop_countdown_n = STOP_COUNTDOWN_SECS
        self._stop_tick()

    def _stop_tick(self):
        if self._stop_countdown_n > 0:
            self._log.append_info(f"Stopping in {self._stop_countdown_n}…")
            self._stop_countdown_n -= 1
            QTimer.singleShot(1000, self._stop_tick)
        else:
            self.stop_server()

    def _restart_after_stop(self):
        if self._resource_restore_pending:
            self._resource_restore_pending = False
            self._restore_snapshot()
        ts = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        s = load_settings()
        s["last_restart"] = ts
        save_settings(s)
        self._server_tab._last_restart_lbl.setText(ts)
        self._restart_countdown_n = 2
        self._restart_tick()

    def _restart_tick(self):
        if self._restart_countdown_n > 0:
            self._log.append_info(f"Restarting in {self._restart_countdown_n}…")
            self._restart_countdown_n -= 1
            QTimer.singleShot(1000, self._restart_tick)
        else:
            self.start_server()

    def _on_server_started(self):
        self._server_tab.set_running(True)
        self._resource_tab.restart_snapshot_btn.setEnabled(True)
        if hasattr(self, "_tray"):
            self._tray.setIcon(make_icon(True))
            self._tray.setToolTip("Enshrouded — Running ✔")
        # During first-run the server writes logs to SERVER_DIR/logs/ before config exists.
        if self._overlay and _needs_first_run_migration():
            if CONFIG_FILE.exists():
                log_str = json.loads(CONFIG_FILE.read_text()).get("logDirectory", "./logs")
                server_log = (SERVER_DIR / log_str).resolve() / "enshrouded_server.log"
            else:
                server_log = SERVER_DIR / "logs" / "enshrouded_server.log"
        else:
            server_log = LOG_DIR / "enshrouded_server.log"
        self._active_log_path = server_log
        self._log_tail_pos = server_log.stat().st_size if server_log.exists() else 0
        self._log_tail_timer.start()
        if self._overlay and _needs_first_run_migration():
            if FIRST_RUN_FAST:
                self._overlay.set_status(
                    "Setting up your server for the first time…\nThis only takes a moment."
                )
                self._fast_first_run_timer.start()
                self._check_fast_first_run()  # config file may already exist
            else:
                self._overlay.set_status(
                    "The server is generating your world for the first time.\n"
                    "This can take several minutes — please wait…"
                )
                self._migration_timer.start()
                self._check_first_run_migration()  # immediate check in case files exist from a prior run

    def _on_server_stopped(self):
        self._log_tail_timer.stop()
        self._force_kill_timer.stop()
        self._migration_timer.stop()
        self._fast_first_run_timer.stop()
        self._resource_tab.restart_snapshot_btn.setEnabled(False)
        self._tail_server_log()
        code = self._process.exitCode()
        status = self._process.exitStatus()
        _QT_FORCE_KILL_CODE = 0xf291
        if status == QProcess.ExitStatus.CrashExit and code == _QT_FORCE_KILL_CODE:
            self._log.append_info("Server stopped.")
        else:
            self._log.append_info(f"Server stopped (exit code {code}).")
        self._server_tab.set_running(False)
        if hasattr(self, "_tray"):
            self._tray.setIcon(make_icon(False))
            self._tray.setToolTip("Enshrouded — Stopped")
        if self._overlay and not self._migration_pending:
            # Server stopped while we were waiting — check immediately for save files
            handled = self._check_first_run_migration()
            if not handled and not self._migration_pending:
                # No saves found — server exited before generating the world
                code = self._process.exitCode()
                self._overlay.set_status(
                    f"The server stopped (exit code {code}) before generating a world.\n\n"
                    "Check the Logs tab for the server's output — it will show the exact error.\n\n"
                    "Common causes: missing Visual C++ Redistributable 2022 x64, "
                    "port 15636/15637 already in use, or antivirus blocking the server binary.\n\n"
                    "Resolve the issue, then click Start Server, or click Skip Setup to dismiss."
                )
                self._overlay.hide_progress()
                self._overlay.show_log_button()
                self._overlay.show_skip_button()

        if self._migration_pending:
            self._migration_pending = False
            self._finish_first_run_setup()

    def _tail_server_log(self):
        server_log = self._active_log_path
        if not server_log.exists():
            return
        try:
            if server_log.stat().st_size < self._log_tail_pos:
                self._log_tail_pos = 0  # log was rotated/truncated at server start
            with open(server_log, "r", errors="replace") as f:
                f.seek(self._log_tail_pos)
                new = f.read()
                self._log_tail_pos = f.tell()
            if new:
                self._log.append_plain(new)
                if 'Machines:' in new:
                    machines = MACHINE_RE.findall(new)
                    if machines:
                        players = sum(1 for idx, _, _ in machines if int(idx) > 0)
                        last = machines[-1]
                        self._server_tab.set_session_info(players, int(last[1]), last[2])
        except OSError:
            pass

    def _on_stdout(self):
        text = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        if text.strip():
            self._log.append_info(text)

    def _on_stderr(self):
        text = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        if text.strip():
            self._log.append_info(text)

    def _load_schedule(self):
        s = load_settings()
        self._server_tab._sched_enable.setChecked(s.get("scheduled_restart_enabled", False))
        t = QTime.fromString(s.get("scheduled_restart_time", "04:00"), "HH:mm")
        self._server_tab._sched_time.setTime(t if t.isValid() else QTime(4, 0))
        last = s.get("last_restart", "—")
        self._server_tab._last_restart_lbl.setText(last)
        self._update_next_restart_label()

    def _save_schedule(self):
        s = load_settings()
        s["scheduled_restart_enabled"] = self._server_tab._sched_enable.isChecked()
        s["scheduled_restart_time"] = self._server_tab._sched_time.time().toString("HH:mm")
        save_settings(s)
        self._update_next_restart_label()

    def _update_next_restart_label(self):
        if not self._server_tab._sched_enable.isChecked():
            self._server_tab._sched_next.setText("Disabled")
            return
        t = self._server_tab._sched_time.time()
        now = datetime.now()
        nxt = now.replace(hour=t.hour(), minute=t.minute(), second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        self._server_tab._sched_next.setText(nxt.strftime("%Y-%m-%d %I:%M %p"))

    def _check_scheduled_restart(self):
        if self._resource_tab.is_enabled():
            return
        if not self._server_tab._sched_enable.isChecked():
            return
        if not self._is_running():
            return
        t = self._server_tab._sched_time.time()
        now = datetime.now()
        if now.hour == t.hour() and now.minute == t.minute():
            today = now.date()
            if self._scheduled_restart_date != today:
                self._scheduled_restart_date = today
                self._log.append_info(f"Scheduled daily restart triggered at {now.strftime('%H:%M')}")
                self._update_next_restart_label()
                self.restart_server()

    def _apply_resource_group(self):
        """Inject or remove the 'Resource' user group from CONFIG_FILE only (not world config)."""
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            # Strip any previously injected Resource group
            groups = [g for g in data.get("userGroups", []) if g.get("name") != "Resource"]
            if self._resource_tab.is_enabled():
                password = self._resource_tab._password_edit.text().strip()
                groups.append({
                    "name": "Resource",
                    "password": password,
                    "canKickBan": False,
                    "canAccessInventories": True,
                    "canEditWorld": False,
                    "canEditBase": False,
                    "canExtendBase": False,
                    "reservedSlots": 0,
                })
            data["userGroups"] = groups
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=4)
        except (OSError, json.JSONDecodeError):
            pass

    def _manual_resource_restart(self):
        if not self._resource_tab.snapshot_folder():
            QMessageBox.warning(self, "No Snapshot Selected",
                "Please select a snapshot world before restarting with snapshot.")
            return
        self._log.append_info("Manual snapshot restart triggered.")
        self._resource_restore_pending = True
        self.restart_server()

    def _on_resource_mode_changed(self, enabled: bool):
        if enabled:
            if self._resource_tab.interval_minutes() < 1:
                QMessageBox.warning(self, "Invalid Interval",
                    "Please set a reset interval of at least 1 minute.")
                self._resource_tab._enabled_cb.blockSignals(True)
                self._resource_tab._enabled_cb.setChecked(False)
                self._resource_tab._enabled_cb.blockSignals(False)
                return
            if not self._resource_tab.snapshot_folder():
                QMessageBox.warning(self, "No Snapshot Selected",
                    "Please select a snapshot world before enabling resource server mode.")
                self._resource_tab._enabled_cb.blockSignals(True)
                self._resource_tab._enabled_cb.setChecked(False)
                self._resource_tab._enabled_cb.blockSignals(False)
                return
            self._resource_next_reset = (
                datetime.now() + timedelta(minutes=self._resource_tab.interval_minutes()))
        else:
            self._resource_next_reset = None
            self._resource_tab._next_reset_lbl.setText("Disabled")
        self._save_resource_settings()

    def _check_resource_restart(self):
        if not self._resource_tab.is_enabled():
            return
        if self._resource_next_reset is None or not self._is_running():
            return
        if datetime.now() >= self._resource_next_reset:
            self._resource_next_reset = (
                datetime.now() + timedelta(minutes=self._resource_tab.interval_minutes()))
            self._save_resource_settings()
            self._log.append_info("Resource server reset triggered — restoring snapshot…")
            self._resource_restore_pending = True
            self.restart_server()

    def _update_resource_next_label(self):
        self._resource_tab.restart_snapshot_btn.setEnabled(self._is_running())
        if not self._resource_tab.is_enabled() or self._resource_next_reset is None:
            return
        delta = self._resource_next_reset - datetime.now()
        total = int(delta.total_seconds())
        if total <= 0:
            self._resource_tab._next_reset_lbl.setText("Resetting…")
            return
        h, r = divmod(total, 3600)
        m, s = divmod(r, 60)
        self._resource_tab._next_reset_lbl.setText(
            f"in {h:02d}:{m:02d}:{s:02d}  ({self._resource_next_reset.strftime('%I:%M %p')})")

    def _restore_snapshot(self):
        import time as _time
        folder = self._resource_tab.snapshot_folder()
        if not folder:
            self._log.append_error("No snapshot world selected — skipping restore.")
            return
        snapshot_dir = WORLDS_DIR / folder
        active_dir = active_world()
        if not active_dir or not snapshot_dir.exists():
            self._log.append_error("Snapshot or active world directory missing — skipping restore.")
            return
        if snapshot_dir.resolve() == active_dir.resolve():
            self._log.append_error("Snapshot world IS the active world — cannot restore.")
            return
        server_hash = None
        for f in snapshot_dir.iterdir():
            if f.name.endswith("-index") and f.is_file():
                server_hash = f.name[:-len("-index")]
                break
        if not server_hash:
            self._log.append_error("Snapshot world has no save files — skipping restore.")
            return
        src_index = snapshot_dir / f"{server_hash}-index"
        try:
            index_data = json.loads(src_index.read_text())
        except (OSError, json.JSONDecodeError):
            self._log.append_error("Cannot read snapshot index — skipping restore.")
            return
        latest = index_data.get("latest", 0)
        src_save = snapshot_dir / (server_hash if latest == 0 else f"{server_hash}-{latest}")
        if not src_save.exists():
            self._log.append_error(
                f"Snapshot save file missing ({src_save.name}) — skipping restore.")
            return
        # Always normalize to base file + latest=0 index (same as import logic)
        shutil.copy2(str(src_save), str(active_dir / server_hash))
        new_index = {"latest": 0, "time": int(_time.time()), "deleted": False}
        (active_dir / f"{server_hash}-index").write_text(json.dumps(new_index, indent="\t"))
        nick = load_nicknames().get(folder, folder)
        self._log.append_info(f"Snapshot restored from '{nick}' (slot {latest} → base).")

    def _save_resource_settings(self):
        s = load_settings()
        s["resource_mode_enabled"]     = self._resource_tab.is_enabled()
        s["resource_snapshot_world"]   = self._resource_tab.snapshot_folder() or ""
        s["resource_interval_minutes"] = self._resource_tab.interval_minutes()
        s["resource_password"]         = self._resource_tab._password_edit.text()
        if self._resource_next_reset:
            s["resource_next_reset"] = self._resource_next_reset.isoformat()
        else:
            s.pop("resource_next_reset", None)
        save_settings(s)

    def _load_resource_settings(self):
        s = load_settings()
        minutes = s.get("resource_interval_minutes", 60)
        self._resource_tab._hours_spin.blockSignals(True)
        self._resource_tab._mins_spin.blockSignals(True)
        self._resource_tab._hours_spin.setValue(minutes // 60)
        self._resource_tab._mins_spin.setValue(minutes % 60)
        self._resource_tab._hours_spin.blockSignals(False)
        self._resource_tab._mins_spin.blockSignals(False)
        self._resource_tab._password_edit.blockSignals(True)
        self._resource_tab._password_edit.setText(s.get("resource_password", ""))
        self._resource_tab._password_edit.blockSignals(False)
        folder = s.get("resource_snapshot_world", "")
        if folder:
            idx = self._resource_tab._snapshot_combo.findData(folder)
            if idx >= 0:
                self._resource_tab._snapshot_combo.blockSignals(True)
                self._resource_tab._snapshot_combo.setCurrentIndex(idx)
                self._resource_tab._snapshot_combo.blockSignals(False)
        if s.get("resource_mode_enabled", False):
            next_str = s.get("resource_next_reset", "")
            if next_str:
                try:
                    nxt = datetime.fromisoformat(next_str)
                    self._resource_next_reset = nxt if nxt > datetime.now() else (
                        datetime.now() + timedelta(minutes=max(minutes, 1)))
                except ValueError:
                    self._resource_next_reset = datetime.now() + timedelta(minutes=max(minutes, 1))
            else:
                self._resource_next_reset = datetime.now() + timedelta(minutes=max(minutes, 1))
            self._resource_tab._enabled_cb.blockSignals(True)
            self._resource_tab._enabled_cb.setChecked(True)
            self._resource_tab._enabled_cb.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay:
            self._overlay.setGeometry(0, 0, self.width(), self.height())

    def _check_first_run_migration(self) -> bool:
        """Check whether the server has generated save files; trigger migration when ready.

        Returns True if migration was triggered or handled, False if saves not found yet.
        """
        if not CONFIG_FILE.exists():
            return False
        data = json.loads(CONFIG_FILE.read_text())
        save_str = data.get("saveDirectory", "")
        if not save_str or Path(save_str).is_absolute():
            self._migration_timer.stop()
            return False
        save_path = (SERVER_DIR / save_str).resolve()
        if not save_path.exists() or not any(save_path.iterdir()):
            return False  # world not generated yet
        # Save files exist — trigger migration
        self._migration_timer.stop()
        if self._is_running():
            # Server is running — stop it first; migration runs in _on_server_stopped
            self._migration_pending = True
            if self._overlay:
                self._overlay.set_status("World generated. Stopping server to migrate save files…")
            self._log.append_info("First-run: world generated, stopping server to migrate paths…")
            self._graceful_stop_first_run()
        else:
            # Server already stopped — migrate inline now
            self._finish_first_run_setup()
        return True

    def _graceful_stop_first_run(self):
        """Gracefully stop the server during first-run; migration runs on stop."""
        pid = self._process.processId()
        if sys.platform == "win32":
            if pid <= 0 or not _send_ctrl_c_windows(pid):
                self._process.terminate()
        else:
            os.kill(pid, __import__("signal").SIGINT)
        QTimer.singleShot(15_000, self._force_kill)

    def _check_fast_first_run(self):
        """Fast first-run: as soon as the server has written its config file, stop
        it and migrate paths — no waiting for the world's first autosave."""
        if not CONFIG_FILE.exists():
            return  # config not written yet — keep polling
        self._fast_first_run_timer.stop()
        if self._migration_pending:
            return
        self._migration_pending = True
        if self._overlay:
            self._overlay.set_status("Finishing setup…")
        self._log.append_info("First-run (fast): server config created, finishing setup…")
        # Brief settle so the server finishes writing its config defaults, then stop.
        QTimer.singleShot(5_000, self._stop_for_fast_first_run)

    def _stop_for_fast_first_run(self):
        if not self._migration_pending:
            return  # server already stopped on its own; _on_server_stopped handled it
        if self._is_running():
            self._graceful_stop_first_run()  # migration runs in _on_server_stopped
        else:
            self._migration_pending = False
            self._finish_first_run_setup()

    def _finish_first_run_setup(self):
        """Finalise first-run config, then wait for the user to confirm the restart."""
        self._log.append_info("First-run setup: migrating the generated world…")
        self._do_first_run_migration()
        self._log.append_info("Setup complete. Waiting for user to confirm restart.")
        if self._overlay:
            self._overlay.setup_finished(
                "First-time setup is complete.\n\n"
                "The manager needs to restart to apply it — click below when you're ready."
            )

    def _do_first_run_migration(self):
        """Move server-generated saves/logs into managed paths and update config.

        The graceful Ctrl+C stop flushes the world to disk on shutdown, so by the
        time this runs the first-run world exists and is moved into world_1 — both
        the fast and legacy paths preserve the world the server generated.
        """
        if not CONFIG_FILE.exists():
            return
        data = json.loads(CONFIG_FILE.read_text())
        save_str = data.get("saveDirectory", "")
        log_str  = data.get("logDirectory",  "")

        world_1 = WORLDS_DIR / "world_1"
        world_1.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        moved_saves = 0
        if save_str:
            _sd = Path(save_str)
            src = (_sd if _sd.is_absolute() else (SERVER_DIR / _sd)).resolve()
            if src.exists() and src != world_1:
                for item in src.iterdir():
                    shutil.move(str(item), str(world_1 / item.name))
                    moved_saves += 1
                try:
                    src.rmdir()
                except OSError:
                    pass

        # Fallback: if primary path found nothing, scan SERVER_DIR subdirs for save files.
        if moved_saves == 0:
            for sub in SERVER_DIR.iterdir():
                if not sub.is_dir() or sub == world_1:
                    continue
                has_index = any(
                    f.name.endswith("-index") and f.is_file()
                    for f in sub.iterdir()
                )
                if has_index:
                    self._log.append_info(
                        f"First-run migration: save files found in {sub.name}/ (not in config path). Moving.")
                    for item in sub.iterdir():
                        shutil.move(str(item), str(world_1 / item.name))
                        moved_saves += 1
                    try:
                        sub.rmdir()
                    except OSError:
                        pass
                    break

        self._log.append_info(f"First-run migration: moved {moved_saves} save file(s) to world_1.")

        if log_str:
            _ld = Path(log_str)
            src_log = (_ld if _ld.is_absolute() else (SERVER_DIR / _ld)).resolve()
            if src_log.exists() and src_log != LOG_DIR:
                for item in src_log.iterdir():
                    shutil.move(str(item), str(LOG_DIR / item.name))
                try:
                    src_log.rmdir()
                except OSError:
                    pass

        data["saveDirectory"] = str(world_1)
        data["logDirectory"]  = str(LOG_DIR)
        CONFIG_FILE.write_text(json.dumps(data, indent=4))
        ensure_world_config(world_1)

    def _restart_manager(self):
        """Release the single-instance lock and relaunch this script."""
        global _lock_fh
        if _lock_fh:
            if sys.platform == "win32":
                import msvcrt
                try:
                    _lock_fh.seek(0)
                    msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                fcntl.flock(_lock_fh, fcntl.LOCK_UN)
            _lock_fh.close()
            _lock_fh = None
        (Path(__file__).parent / "manager.pid").unlink(missing_ok=True)
        launcher = "launch.bat" if sys.platform == "win32" else "launch.sh"
        launch = Path(__file__).parent / launcher
        if launch.exists():
            subprocess.Popen([str(launch)], shell=(sys.platform == "win32"))
        else:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
        QApplication.quit()

    def _open_first_run_log(self):
        if self._active_log_path.exists():
            subprocess.Popen(["notepad", str(self._active_log_path)])
        else:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Log Not Found",
                f"No log file found yet at:\n{self._active_log_path}\n\n"
                "The server may have crashed before writing any output.")

    def _dismiss_overlay(self):
        if self._overlay:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def quit_app(self):
        if self._is_running():
            reply = QMessageBox.question(
                self, "Quit",
                "The server is running. Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._process.kill()
            self._process.waitForFinished(5000)
        (Path(__file__).parent / "manager.pid").unlink(missing_ok=True)
        QApplication.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # pythonw.exe discards stdout/stderr, so an uncaught exception from a Qt
    # slot vanishes silently and the process disappears. Log to a file instead.
    import traceback
    _error_log = Path(__file__).parent / "manager_error.log"
    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            with open(_error_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.now().isoformat()} ===\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _excepthook

    migrate_saves_if_needed()
    migrate_world_configs_if_needed()

    # Windows groups the taskbar button (and its icon) by AppUserModelID.
    # Without an explicit ID, Windows uses the host process — pythonw.exe —
    # so the taskbar shows the Python icon. Declaring our own ID makes Windows
    # treat the app as distinct and use the window icon instead.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "YotaPower04.EnshroudedServerManager")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    app.setQuitOnLastWindowClosed(False)
    _icon_path = Path(__file__).parent / "manager.ico"
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))
    elif SERVER_BIN.exists():
        app.setWindowIcon(QIcon(str(SERVER_BIN)))

    # Single-instance lock — held for the lifetime of the process.
    global _lock_fh
    _lock_fh = open(Path(__file__).parent / "manager.lock", "w")
    try:
        if sys.platform == "win32":
            import msvcrt
            _lock_fh.seek(0)
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write PID so the installer (and other scripts) can kill us by PID.
        _pid_file = Path(__file__).parent / "manager.pid"
        _pid_file.write_text(str(os.getpid()))
    except OSError:
        QMessageBox.warning(None, "Already Running",
                            "Enshrouded Server Manager is already running.")
        sys.exit(0)

    import signal as _signal
    _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
    if sys.platform != "win32":
        _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)

    window = MainWindow()

    tray = QSystemTrayIcon(make_icon(False))
    tray.setToolTip("Enshrouded — Stopped")
    window._tray = tray

    menu = QMenu()
    menu.addAction("Open Manager").triggered.connect(window.show)
    menu.addSeparator()
    menu.addAction("Start Server").triggered.connect(window.start_server)
    menu.addAction("Stop Server").triggered.connect(window.stop_server)
    menu.addSeparator()
    menu.addAction("Quit").triggered.connect(window.quit_app)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.show()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    window.show()
    QTimer.singleShot(2000, window.start_server)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
