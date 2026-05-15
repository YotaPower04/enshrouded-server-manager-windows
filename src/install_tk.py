#!/usr/bin/env python3
"""Enshrouded Server Manager — Windows Installer (Tkinter GUI)"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import urllib.request
import urllib.error
import winreg
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW}

ENSHROUDED_APP_ID = "2278520"
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
PY_VERSION = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-amd64.exe"

if getattr(sys, "frozen", False):
    REPO_DIR = Path(sys._MEIPASS)
else:
    REPO_DIR = Path(__file__).parent.resolve()


def _bundled(name: str) -> Path | None:
    """Find a bundled resource — flat in frozen builds, in ../assets when running from src/."""
    for cand in (REPO_DIR / name, REPO_DIR.parent / "assets" / name):
        if cand.exists():
            return cand
    return None

_PYTHON_EXE: str = sys.executable
INSTALL_DIR: Path = None

C_BG   = "#0f0f1a"
C_HDR  = "#1a1a2e"
C_ACC  = "#00d4ff"
C_TXT  = "#e8e8e8"
C_DIM  = "#888888"
C_BTN  = "#1e3a5f"
C_HOVR = "#2a5080"
C_LOG  = "#070710"
C_OK   = "#00c853"
C_WARN = "#ffc107"
C_ERR  = "#f44336"
F_UI   = ("Segoe UI", 10)
F_LOG  = ("Consolas", 9)


class _Err(Exception):
    pass


# ---------------------------------------------------------------------------
# Core installer logic (GUI-callback variant)
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path, label: str, log):
    seen = [-1]
    def hook(n, bs, total):
        if total > 0:
            pct = min(100, n * bs * 100 // total)
            if pct >= seen[0] + 10:
                log(f"  {label}: {pct}%")
                seen[0] = pct
    try:
        urllib.request.urlretrieve(url, dest, reporthook=hook)
        if seen[0] < 100:
            log(f"  {label}: 100%")
    except urllib.error.URLError as e:
        raise _Err(f"Download failed ({label}):\n{e}\nCheck your internet connection.")


def _resolve_python_exe(log):
    global _PYTHON_EXE
    if not getattr(sys, "frozen", False):
        _PYTHON_EXE = sys.executable
        return

    for cand in ("py", "python", "python3"):
        path = shutil.which(cand)
        if not path:
            continue
        try:
            r = subprocess.run([path, "-c", "import sys; print(sys.executable)"],
                               capture_output=True, text=True, timeout=10,
                               **_NO_WINDOW)
            if r.returncode == 0:
                found = r.stdout.strip()
                if found and Path(found).exists():
                    _PYTHON_EXE = found
                    log(f"[OK] Python found: {Path(found).name}")
                    return
        except (OSError, subprocess.TimeoutExpired):
            continue

    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        base = Path(local_app) / "Programs" / "Python"
        if base.exists():
            for sub in sorted(base.iterdir(), reverse=True):
                exe = sub / "python.exe"
                if exe.exists():
                    _PYTHON_EXE = str(exe)
                    log(f"[OK] Python found: {exe.parent.name}")
                    return

    log(f"Python not found — downloading Python {PY_VERSION}...")
    tmp = Path(os.environ.get("TEMP", ".")) / f"python-{PY_VERSION}-amd64.exe"
    _download(PY_URL, tmp, f"Python {PY_VERSION}", log)
    log(f"Installing Python {PY_VERSION} (no admin required)...")
    r = subprocess.run(
        [str(tmp), "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"],
        check=False, **_NO_WINDOW,
    )
    try:
        tmp.unlink()
    except OSError:
        pass
    if r.returncode != 0:
        raise _Err(f"Python installer failed (exit {r.returncode}).\n"
                   "Install Python 3.8+ manually from https://python.org")
    log(f"[OK] Python {PY_VERSION} installed.")

    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        base = Path(local_app) / "Programs" / "Python"
        if base.exists():
            for sub in sorted(base.iterdir(), reverse=True):
                exe = sub / "python.exe"
                if exe.exists():
                    _PYTHON_EXE = str(exe)
                    return
    raise _Err("Python installed but could not be located. Re-run the installer.")


def _vcredist_installed():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")
        val, _ = winreg.QueryValueEx(key, "Installed")
        winreg.CloseKey(key)
        return val == 1
    except OSError:
        return False


def _install_vcredist(log):
    if _vcredist_installed():
        log("[OK] Visual C++ 2022 x64: already installed.")
        return
    log("Downloading Visual C++ Redistributable 2022 x64...")
    dest = Path(os.environ.get("TEMP", ".")) / "vc_redist.x64.exe"
    _download(VCREDIST_URL, dest, "vc_redist.x64.exe", log)
    log("Installing Visual C++ Redistributable...")
    r = subprocess.run([str(dest), "/install", "/quiet", "/norestart"], check=False, **_NO_WINDOW)
    try:
        dest.unlink()
    except OSError:
        pass
    if r.returncode not in (0, 3010):
        log(f"[WARN] VC++ installer returned {r.returncode} — server may not start correctly.")
    else:
        log("[OK] Visual C++ Redistributable 2022 x64 installed.")


def _create_dirs(log):
    log("Creating directory structure...")
    for sub in ["server", "saves\\worlds", "saves\\logs", "steamcmd"]:
        (INSTALL_DIR / sub).mkdir(parents=True, exist_ok=True)
    log("[OK] Directories created.")


def _install_steamcmd(log):
    log("Downloading SteamCMD...")
    sdir = INSTALL_DIR / "steamcmd"
    zpath = sdir / "steamcmd.zip"
    _download(STEAMCMD_URL, zpath, "steamcmd.zip", log)
    with zipfile.ZipFile(zpath, "r") as zf:
        zf.extractall(sdir)
    zpath.unlink(missing_ok=True)
    exe = sdir / "steamcmd.exe"
    if not exe.exists():
        raise _Err("steamcmd.exe not found after extraction — download may be corrupted.")
    log("Running SteamCMD self-update (may take a moment)...")
    subprocess.run([str(exe), "+quit"], cwd=str(sdir), check=False, **_NO_WINDOW)
    subprocess.run([str(exe), "+quit"], cwd=str(sdir), check=False, **_NO_WINDOW)
    log("Priming SteamCMD for Windows platform downloads...")
    subprocess.run([str(exe), "+@sSteamCmdForcePlatformType", "windows", "+quit"],
                   cwd=str(sdir), check=False, **_NO_WINDOW)
    log("[OK] SteamCMD ready.")


def _download_server(log):
    log("Downloading Enshrouded Dedicated Server (~7 GB, may take several minutes)...")
    steamcmd = INSTALL_DIR / "steamcmd" / "steamcmd.exe"
    sdir = INSTALL_DIR / "server"
    cmd = [
        str(steamcmd),
        "+@sSteamCmdForcePlatformType", "windows",
        "+force_install_dir", str(sdir),
        "+login", "anonymous",
        "+app_update", ENSHROUDED_APP_ID, "validate",
        "+quit",
    ]
    r = subprocess.run(cmd, cwd=str(INSTALL_DIR / "steamcmd"), **_NO_WINDOW)
    server_bin = sdir / "enshrouded_server.exe"
    if not server_bin.exists():
        log("[WARN] Download incomplete — retrying (attempt 2 of 2)...")
        log("       This may take several more minutes — please wait.")
        r = subprocess.run(cmd, cwd=str(INSTALL_DIR / "steamcmd"), **_NO_WINDOW)
    if not server_bin.exists():
        raise _Err(
            f"enshrouded_server.exe not found (exit {r.returncode}).\n\n"
            "Common causes:\n"
            "  • Antivirus blocked steamcmd.exe — check quarantine\n"
            "  • No internet / Steam servers unreachable\n"
            "  • Disk full\n\n"
            "Re-run the installer once resolved."
        )
    log("[OK] Enshrouded Dedicated Server downloaded.")


def _setup_manager(log):
    log("Creating Python virtual environment...")
    subprocess.run([_PYTHON_EXE, "-m", "venv", str(INSTALL_DIR / "venv")], check=True, **_NO_WINDOW)
    log("[OK] venv created.")

    pip = INSTALL_DIR / "venv" / "Scripts" / "pip.exe"
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=False, capture_output=True, **_NO_WINDOW)

    log("Installing PyQt6 (this may take a minute)...")
    subprocess.run([str(pip), "install", "PyQt6"], check=True, **_NO_WINDOW)
    log("[OK] PyQt6 installed.")

    pid_file = INSTALL_DIR / "manager.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, **_NO_WINDOW)
            pid_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    log("Copying manager script...")
    shutil.copy2(REPO_DIR / "enshrouded_manager.py", INSTALL_DIR / "enshrouded_manager.py")
    for ico in ("manager.ico", "running.ico"):
        src = _bundled(ico)
        if src:
            shutil.copy2(src, INSTALL_DIR / ico)
    log("[OK] Manager script copied.")

    (INSTALL_DIR / "install.json").write_text(
        json.dumps({"install_dir": str(INSTALL_DIR)}, indent=4) + "\n"
    )
    (INSTALL_DIR / "launch.bat").write_text(
        "@echo off\n"
        'start "" "%~dp0venv\\Scripts\\pythonw.exe" "%~dp0enshrouded_manager.py"\n',
        encoding="utf-8",
    )
    log("[OK] launch.bat written.")


def _create_shortcut(target: Path, args: str, shortcut_path: Path,
                     description: str = "", icon: Path | None = None):
    icon_line = f"$s.IconLocation = '{icon}, 0'; " if (icon and icon.exists()) else ""
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.Arguments = '\"{args}\"'; "
        f"$s.WorkingDirectory = '{target.parent}'; "
        f"$s.Description = '{description}'; "
        f"{icon_line}"
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   capture_output=True, check=False, **_NO_WINDOW)


def _apply_options(desktop: bool, start_menu: bool, autostart: bool, firewall: bool):
    pythonw  = INSTALL_DIR / "venv" / "Scripts" / "pythonw.exe"
    manager  = INSTALL_DIR / "enshrouded_manager.py"
    icon     = INSTALL_DIR / "manager.ico"
    if not icon.exists():
        icon = INSTALL_DIR / "server" / "enshrouded_server.exe"
    desc     = "Enshrouded Dedicated Server Manager"
    appdata  = os.environ.get("APPDATA", "")
    sm_base  = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    if desktop:
        d = Path.home() / "Desktop"
        if d.exists():
            _create_shortcut(pythonw, str(manager), d / "Enshrouded Server Manager.lnk", desc, icon)

    if start_menu and sm_base.exists():
        _create_shortcut(pythonw, str(manager), sm_base / "Enshrouded Server Manager.lnk", desc, icon)

    if autostart:
        su = sm_base / "Startup"
        if su.exists():
            _create_shortcut(pythonw, str(manager), su / "Enshrouded Server Manager.lnk", desc, icon)

    if firewall:
        for port in (15636, 15637):
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name=Enshrouded Server UDP {port}", "protocol=UDP",
                 "dir=in", f"localport={port}", "action=allow", "enable=yes"],
                capture_output=True, **_NO_WINDOW,
            )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def _btn(parent, text, cmd, width=12):
    b = tk.Button(parent, text=text, command=cmd, bg=C_BTN, fg=C_TXT,
                  activebackground=C_HOVR, activeforeground="white",
                  relief="flat", font=F_UI, width=width, cursor="hand2", padx=10, pady=6)
    return b


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Enshrouded Server Manager — Installer")
        self.resizable(False, False)
        self.configure(bg=C_BG)
        self._center(600, 520)
        self._q: queue.Queue = queue.Queue()

        hdr = tk.Frame(self, bg=C_HDR, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="ENSHROUDED SERVER MANAGER", bg=C_HDR, fg=C_ACC,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=20, pady=(14, 0))
        tk.Label(hdr, text=" — Windows Installer", bg=C_HDR, fg=C_DIM,
                 font=("Segoe UI", 10)).pack(side="left", pady=(20, 0))

        con = tk.Frame(self, bg=C_BG)
        con.pack(fill="both", expand=True)
        con.grid_rowconfigure(0, weight=1)
        con.grid_columnconfigure(0, weight=1)

        self._pages: dict[str, tk.Frame] = {}
        for Cls in (WelcomePage, DirPage, ProgressPage, OptionsPage, InfoPage, DonePage):
            pg = Cls(con, self)
            self._pages[Cls.__name__] = pg
            pg.grid(row=0, column=0, sticky="nsew")

        self.show("WelcomePage")
        self.after(40, self._poll)

    def _center(self, w, h):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def show(self, name: str):
        pg = self._pages[name]
        pg.tkraise()
        if hasattr(pg, "on_show"):
            pg.on_show()

    def _poll(self):
        try:
            while True:
                kind, data = self._q.get_nowait()
                pp = self._pages["ProgressPage"]
                if kind == "log":
                    pp.append(data)
                elif kind == "done":
                    pp.finish()
                    self.show("OptionsPage")
                elif kind == "error":
                    pp.finish()
                    messagebox.showerror("Installation Failed", data, parent=self)
                    self.destroy()
        except queue.Empty:
            pass
        self.after(40, self._poll)

    def q_log(self, msg):   self._q.put(("log", msg))
    def q_done(self):        self._q.put(("done", None))
    def q_error(self, msg): self._q.put(("error", msg))


class WelcomePage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        tk.Label(self, text="⚙", bg=C_BG, fg=C_ACC, font=("Segoe UI", 52)).pack(pady=(32, 6))
        tk.Label(self, text="Welcome to the Enshrouded\nServer Manager Installer",
                 bg=C_BG, fg=C_TXT, font=("Segoe UI", 13, "bold"), justify="center").pack()
        tk.Label(self,
                 text=(
                     "\nThis installer will download and configure:\n\n"
                     "   •  SteamCMD\n"
                     "   •  Enshrouded Dedicated Server  (~7 GB)\n"
                     "   •  Server Manager app  (PyQt6)\n\n"
                     "An internet connection is required."
                 ),
                 bg=C_BG, fg=C_DIM, font=F_UI, justify="left").pack(pady=4)

        bot = tk.Frame(self, bg=C_BG)
        bot.pack(side="bottom", anchor="e", padx=20, pady=16)
        _btn(bot, "Next  →", lambda: app.show("DirPage"), width=10).pack()


class DirPage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        tk.Label(self, text="Choose install location", bg=C_BG, fg=C_TXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=24, pady=(28, 4))
        tk.Label(self,
                 text="All server files, saves, and manager files will live here.\n"
                      "Requires approximately 8–15 GB of free disk space.",
                 bg=C_BG, fg=C_DIM, font=F_UI, justify="left").pack(anchor="w", padx=24, pady=(0, 14))

        row = tk.Frame(self, bg=C_BG)
        row.pack(fill="x", padx=24)
        self._dir = tk.StringVar(value=str(Path.home() / "enshrouded-server"))
        tk.Entry(row, textvariable=self._dir, bg="#12121e", fg=C_TXT,
                 insertbackground=C_TXT, font=F_UI, relief="flat", bd=4).pack(side="left", fill="x", expand=True)
        _btn(row, "Browse…", self._browse, width=10).pack(side="left", padx=(8, 0))

        bot = tk.Frame(self, bg=C_BG)
        bot.pack(side="bottom", fill="x", padx=20, pady=16)
        _btn(bot, "← Back", lambda: app.show("WelcomePage"), width=8).pack(side="left")
        _btn(bot, "Install  →", self._start, width=12).pack(side="right")

    def _browse(self):
        d = filedialog.askdirectory(parent=self._app, title="Choose install directory",
                                    initialdir=self._dir.get())
        if d:
            self._dir.set(d)

    def _start(self):
        global INSTALL_DIR
        raw = self._dir.get().strip()
        if not raw:
            messagebox.showwarning("No directory", "Please choose an install directory.", parent=self._app)
            return
        INSTALL_DIR = Path(raw).expanduser().resolve()
        if INSTALL_DIR.exists() and any(INSTALL_DIR.iterdir()):
            if not messagebox.askyesno(
                "Directory not empty",
                f"{INSTALL_DIR}\n\nThis folder already has files in it. Continue anyway?",
                parent=self._app,
            ):
                return
        self._app.show("ProgressPage")


class ProgressPage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        tk.Label(self, text="Installing…", bg=C_BG, fg=C_TXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=24, pady=(18, 6))

        self._bar = ttk.Progressbar(self, mode="indeterminate", length=552)
        self._bar.pack(padx=24, fill="x")

        self._log = ScrolledText(self, bg=C_LOG, fg=C_TXT, font=F_LOG,
                                 relief="flat", state="disabled", wrap="word", height=18)
        self._log.pack(fill="both", expand=True, padx=24, pady=(10, 4))
        self._log.tag_config("ok",   foreground=C_OK)
        self._log.tag_config("warn", foreground=C_WARN)
        self._log.tag_config("err",  foreground=C_ERR)

        self._status = tk.Label(self, text="", bg=C_BG, fg=C_DIM, font=F_UI)
        self._status.pack(pady=(0, 8))

    def on_show(self):
        self._bar.start(10)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            _resolve_python_exe(self._app.q_log)
            _install_vcredist(self._app.q_log)
            _create_dirs(self._app.q_log)
            _install_steamcmd(self._app.q_log)
            _download_server(self._app.q_log)
            _setup_manager(self._app.q_log)
        except _Err as e:
            self._app.q_error(str(e))
            return
        except Exception as e:
            self._app.q_error(f"Unexpected error:\n{e}")
            return
        self._app.q_done()

    def append(self, msg: str):
        self._log.configure(state="normal")
        tag = ("ok" if "[OK]" in msg
               else "warn" if "[WARN]" in msg
               else "err" if "[ERR]" in msg
               else "")
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def finish(self):
        self._bar.stop()
        self._bar.configure(mode="determinate", value=100)
        self._status.configure(text="Done.", fg=C_OK)


class OptionsPage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        tk.Label(self, text="Almost done!", bg=C_BG, fg=C_OK,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(self, text="Configure optional settings, then click Finish.",
                 bg=C_BG, fg=C_DIM, font=F_UI).pack(anchor="w", padx=24, pady=(0, 14))

        self._desktop   = tk.BooleanVar(value=True)
        self._startmenu = tk.BooleanVar(value=True)
        self._autostart = tk.BooleanVar(value=False)
        self._firewall  = tk.BooleanVar(value=True)

        opts = [
            ("Create desktop shortcut",                        self._desktop),
            ("Add to Start Menu",                              self._startmenu),
            ("Launch manager automatically on Windows login",  self._autostart),
            ("Add Windows Firewall rules  (UDP 15636, 15637)", self._firewall),
        ]
        for text, var in opts:
            tk.Checkbutton(self, text=text, variable=var, bg=C_BG, fg=C_TXT,
                           selectcolor=C_HDR, activebackground=C_BG,
                           activeforeground=C_TXT, font=F_UI).pack(anchor="w", padx=36, pady=3)

        tk.Label(self,
                 text="\nPort forwarding: forward UDP 15636 and 15637 on your router\n"
                      "to allow players outside your local network to connect.",
                 bg=C_BG, fg=C_DIM, font=F_UI, justify="left").pack(anchor="w", padx=24, pady=(8, 0))

        bot = tk.Frame(self, bg=C_BG)
        bot.pack(side="bottom", anchor="e", padx=20, pady=16)
        _btn(bot, "Finish  →", self._finish, width=12).pack()

    def _finish(self):
        try:
            _apply_options(
                self._desktop.get(),
                self._startmenu.get(),
                self._autostart.get(),
                self._firewall.get(),
            )
        except Exception:
            pass
        self._app.show("InfoPage")


class InfoPage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        import socket as _socket

        try:
            local_ip = _socket.gethostbyname(_socket.gethostname())
        except Exception:
            local_ip = "<your local IP>"

        canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=10)

        inner = tk.Frame(canvas, bg=C_BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        _wrap_labels: list[tk.Label] = []

        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
            wl = max(200, e.width - 32)
            for lbl in _wrap_labels:
                lbl.configure(wraplength=wl)
        canvas.bind("<MouseWheel>", _scroll)
        canvas.bind("<Configure>", _on_resize)
        inner.bind("<MouseWheel>", _scroll)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _section(text):
            lbl = tk.Label(inner, text=text, bg=C_BG, fg=C_ACC, font=("Segoe UI", 11, "bold"))
            lbl.pack(anchor="w", pady=(14, 4))
            lbl.bind("<MouseWheel>", _scroll)
            sep = tk.Frame(inner, bg=C_ACC, height=1)
            sep.pack(fill="x", pady=(0, 6))
            sep.bind("<MouseWheel>", _scroll)

        def _para(text):
            lbl = tk.Label(inner, text=text, bg=C_BG, fg=C_TXT, font=F_UI,
                           justify="left", wraplength=520)
            lbl.pack(anchor="w", fill="x", padx=4, pady=2)
            lbl.bind("<MouseWheel>", _scroll)
            _wrap_labels.append(lbl)

        def _bullet(text):
            lbl = tk.Label(inner, text=f"  •  {text}", bg=C_BG, fg=C_DIM, font=F_UI,
                           justify="left", wraplength=500)
            lbl.pack(anchor="w", fill="x", padx=8)
            lbl.bind("<MouseWheel>", _scroll)
            _wrap_labels.append(lbl)

        _section("First Startup")
        _para(
            "On first launch, the server starts automatically and runs for about "
            "30 seconds to generate its initial world and configuration files.\n\n"
            "A setup overlay will appear — wait until the \"Complete Setup Now\" "
            "button becomes available, then click it. The server will save and shut "
            "down, and the manager will restart normally."
        )

        _section("Port Forwarding")
        _para(
            "Players outside your local network can only connect if you forward two "
            "UDP ports on your router to this machine:"
        )
        port_lbl = tk.Label(inner, text="    UDP  15636  —  Game traffic\n    UDP  15637  —  Steam server query",
                            bg=C_BG, fg=C_ACC, font=("Consolas", 10))
        port_lbl.pack(anchor="w", padx=16, pady=6)
        port_lbl.bind("<MouseWheel>", _scroll)
        _para("How to set up port forwarding:")
        for step in [
            "Log in to your router's admin page  (usually 192.168.1.1 or 192.168.0.1 — check the label on your router).",
            "Find the section labelled \"Port Forwarding\", \"Virtual Server\", or \"NAT\".",
            f"Add two UDP rules for ports 15636 and 15637, pointing to this machine:  {local_ip}",
            "For a permanent setup, assign this machine a static IP via DHCP reservation so the rules stay valid after reboots.",
        ]:
            _bullet(step)

        ip_lbl = tk.Label(inner, text=f"\nThis machine's current local IP:  {local_ip}",
                          bg=C_BG, fg=C_WARN, font=("Segoe UI", 10, "bold"))
        ip_lbl.pack(anchor="w", fill="x", padx=4, pady=(8, 0))
        ip_lbl.bind("<MouseWheel>", _scroll)
        _wrap_labels.append(ip_lbl)

        bot = tk.Frame(self, bg=C_BG)
        bot.pack(side="bottom", anchor="e", padx=20, pady=12)
        _btn(bot, "Finish  →", lambda: app.show("DonePage"), width=12).pack()


class DonePage(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=C_BG)
        self._app = app

        tk.Label(self, text="✓", bg=C_BG, fg=C_OK, font=("Segoe UI", 52)).pack(pady=(36, 6))
        tk.Label(self, text="Installation complete!", bg=C_BG, fg=C_TXT,
                 font=("Segoe UI", 14, "bold")).pack()
        tk.Label(self, text="Double-click  launch.bat  inside the install folder\n"
                            "to start the server manager.", bg=C_BG, fg=C_DIM,
                 font=F_UI, justify="center").pack(pady=10)
        self._path = tk.Label(self, text="", bg=C_BG, fg=C_ACC, font=F_UI)
        self._path.pack()

        bot = tk.Frame(self, bg=C_BG)
        bot.pack(side="bottom", pady=24)
        _btn(bot, "Open Folder",    self._open,    width=14).pack(side="left", padx=8)
        _btn(bot, "Launch Manager", self._launch,  width=16).pack(side="left", padx=8)
        _btn(bot, "Close",          app.destroy,   width=10).pack(side="left", padx=8)

    def on_show(self):
        if INSTALL_DIR:
            self._path.configure(text=str(INSTALL_DIR))

    def _open(self):
        if INSTALL_DIR and INSTALL_DIR.exists():
            subprocess.Popen(["explorer", str(INSTALL_DIR)])

    def _launch(self):
        pythonw = INSTALL_DIR / "venv" / "Scripts" / "pythonw.exe"
        manager = INSTALL_DIR / "enshrouded_manager.py"
        if pythonw.exists() and manager.exists():
            subprocess.Popen([str(pythonw), str(manager)])
        self._app.destroy()


def main():
    if sys.platform != "win32":
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", "This installer is for Windows only.")
        sys.exit(1)
    os.system("")
    App().mainloop()


if __name__ == "__main__":
    main()
