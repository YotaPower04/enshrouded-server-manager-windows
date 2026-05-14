#!/usr/bin/env python3
"""
Enshrouded Dedicated Server Manager — Windows Installer
Run with:  python install.py
Requires:  Python 3.8+, Windows 10 or newer, internet connection.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

ENSHROUDED_APP_ID = "2278520"
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

REPO_DIR = Path(__file__).parent.resolve()
INSTALL_DIR: Path = None  # set by choose_install_dir()

# Enable ANSI color codes in Windows 10+ console
os.system("")

RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
NC     = "\033[0m"

def info(msg):    print(f"{CYAN}[INFO]{NC} {msg}", flush=True)
def success(msg): print(f"{GREEN}[ OK ]{NC} {msg}", flush=True)
def warn(msg):    print(f"{YELLOW}[WARN]{NC} {msg}", flush=True)
def die(msg):
    print(f"{RED}[ERR ]{NC} {msg}", file=sys.stderr)
    input("\nPress Enter to exit...")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 1: Verify prerequisites
# ---------------------------------------------------------------------------
def check_prerequisites():
    info("Checking prerequisites...")

    if sys.version_info < (3, 8):
        die(f"Python 3.8 or newer is required (found {sys.version.split()[0]}).\n"
            "       Download the latest Python from https://python.org")
    success(f"Python: {sys.version.split()[0]}")

    try:
        import venv  # noqa: F401
        success("Python venv: OK")
    except ImportError:
        die("Python venv module is missing. Reinstall Python and ensure the\n"
            "       'py launcher' and 'Add python.exe to PATH' options are checked.")


# ---------------------------------------------------------------------------
# Step 2: Choose install directory
# ---------------------------------------------------------------------------
def choose_install_dir():
    global INSTALL_DIR
    print()
    print("Where would you like to install the Enshrouded server?")
    print("All server files, saves, and manager files will live inside this folder.")
    print()
    default_dir = Path.home() / "enshrouded-server"
    raw = input(f"Install directory [{default_dir}]: ").strip()
    INSTALL_DIR = Path(raw).expanduser().resolve() if raw else default_dir.resolve()

    if INSTALL_DIR.exists() and any(INSTALL_DIR.iterdir()):
        warn(f"Directory already exists and is not empty: {INSTALL_DIR}")
        confirm = input("Continue anyway? [y/N]: ").strip().lower()
        if confirm != "y":
            info("Aborted.")
            sys.exit(0)

    print()
    info(f"Install directory: {INSTALL_DIR}")


# ---------------------------------------------------------------------------
# Step 3: Create directory layout
# ---------------------------------------------------------------------------
def create_dirs():
    info("Creating directory structure...")
    for sub in ["server", "saves\\worlds", "saves\\logs", "steamcmd"]:
        (INSTALL_DIR / sub).mkdir(parents=True, exist_ok=True)
    success("Directories created.")


# ---------------------------------------------------------------------------
# Step 4: Download and extract SteamCMD
# ---------------------------------------------------------------------------
def _download_with_progress(url: str, dest: Path, label: str):
    def _hook(count, block_size, total_size):
        if total_size > 0:
            pct = min(100, count * block_size * 100 // total_size)
            print(f"\r  {label}: {pct}%  ", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, dest, reporthook=_hook)
    except urllib.error.URLError as e:
        die(f"Download failed ({url}):\n       {e}\n       Check your internet connection.")
    print()


def install_steamcmd():
    info("Downloading SteamCMD...")
    steamcmd_dir = INSTALL_DIR / "steamcmd"
    zip_path = steamcmd_dir / "steamcmd.zip"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"

    _download_with_progress(STEAMCMD_URL, zip_path, "Downloading steamcmd.zip")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(steamcmd_dir)
    zip_path.unlink(missing_ok=True)

    if not steamcmd_exe.exists():
        die("steamcmd.exe not found after extraction — download may have been corrupted.")

    info("Running SteamCMD initial self-update (this is normal)...")
    subprocess.run([str(steamcmd_exe), "+quit"], cwd=str(steamcmd_dir), check=False)
    success("SteamCMD installed.")


# ---------------------------------------------------------------------------
# Step 5: Download Enshrouded Dedicated Server via SteamCMD
# ---------------------------------------------------------------------------
def download_server():
    info("Downloading Enshrouded Dedicated Server (this may take several minutes)...")
    steamcmd_exe = INSTALL_DIR / "steamcmd" / "steamcmd.exe"
    server_dir = INSTALL_DIR / "server"

    result = subprocess.run(
        [
            str(steamcmd_exe),
            "+force_install_dir", str(server_dir),
            "+login", "anonymous",
            "+app_update", ENSHROUDED_APP_ID, "validate",
            "+quit",
        ],
        cwd=str(INSTALL_DIR / "steamcmd"),
    )

    server_exe = server_dir / "enshrouded_server.exe"
    if not server_exe.exists():
        die(
            f"enshrouded_server.exe not found after download.\n"
            f"       SteamCMD exit code: {result.returncode}\n"
            f"       Try running install.py again — SteamCMD downloads sometimes need a retry."
        )
    success("Enshrouded Dedicated Server downloaded.")


# ---------------------------------------------------------------------------
# Helper: stop a running manager instance before updating files
# ---------------------------------------------------------------------------
def stop_running_manager():
    pid_file = INSTALL_DIR / "manager.pid"
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return

    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
    )
    if result.returncode == 0:
        info(f"Stopped running manager (PID {pid}).")
    pid_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Step 6: Python venv, PyQt6, manager script, install.json, launch.bat
# ---------------------------------------------------------------------------
def setup_manager():
    info("Creating Python virtual environment...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(INSTALL_DIR / "venv")],
        check=True,
    )
    success("venv created.")

    pip = INSTALL_DIR / "venv" / "Scripts" / "pip.exe"
    info("Installing PyQt6 (this may take a minute)...")
    subprocess.run([str(pip), "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([str(pip), "install", "--quiet", "PyQt6"], check=True)
    success("PyQt6 installed.")

    info("Copying manager script...")
    stop_running_manager()
    shutil.copy2(REPO_DIR / "enshrouded_manager.py", INSTALL_DIR / "enshrouded_manager.py")
    success("Manager script copied.")

    info("Writing install.json...")
    cfg = {"install_dir": str(INSTALL_DIR)}
    (INSTALL_DIR / "install.json").write_text(json.dumps(cfg, indent=4) + "\n")
    info(f"  install_dir: {INSTALL_DIR}")

    info("Writing launch.bat...")
    (INSTALL_DIR / "launch.bat").write_text(
        "@echo off\n"
        'start "" "%~dp0venv\\Scripts\\pythonw.exe" "%~dp0enshrouded_manager.py"\n',
        encoding="utf-8",
    )
    success("launch.bat written.")


# ---------------------------------------------------------------------------
# Step 7: Optional desktop shortcut, Start Menu entry, autostart
# ---------------------------------------------------------------------------
def _create_shortcut(target: Path, args: str, shortcut_path: Path, description: str = ""):
    """Create a Windows .lnk shortcut via PowerShell WScript.Shell."""
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.Arguments = '\"{args}\"'; "
        f"$s.WorkingDirectory = '{target.parent}'; "
        f"$s.Description = '{description}'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        check=False,
    )


def setup_shortcuts():
    print()
    yn = input("Create desktop shortcut? [Y/n]: ").strip().lower()
    if yn == "n":
        return

    pythonw = INSTALL_DIR / "venv" / "Scripts" / "pythonw.exe"
    manager = INSTALL_DIR / "enshrouded_manager.py"
    desc = "Enshrouded Dedicated Server Manager"

    desktop = Path.home() / "Desktop"
    if desktop.exists():
        shortcut = desktop / "Enshrouded Server Manager.lnk"
        _create_shortcut(pythonw, str(manager), shortcut, desc)
        success(f"Desktop shortcut: {shortcut}")

    app_data = os.environ.get("APPDATA", "")
    start_menu = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if start_menu.exists():
        shortcut = start_menu / "Enshrouded Server Manager.lnk"
        _create_shortcut(pythonw, str(manager), shortcut, desc)
        success(f"Start Menu entry: {shortcut}")

    yn2 = input("Launch manager automatically on Windows login? [y/N]: ").strip().lower()
    if yn2 == "y":
        startup = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup.exists():
            shortcut = startup / "Enshrouded Server Manager.lnk"
            _create_shortcut(pythonw, str(manager), shortcut, desc)
            success(f"Startup entry: {shortcut}")


# ---------------------------------------------------------------------------
# Step 8: Optional Windows Firewall rules
# ---------------------------------------------------------------------------
def setup_firewall():
    print()
    print("Windows Firewall rules are needed so players on your network can connect.")
    yn = input("Add firewall rules for UDP 15636 and 15637? [Y/n]: ").strip().lower()
    if yn == "n":
        warn("Skipped — players may not be able to connect until you add the rules manually.")
        return

    all_ok = True
    for port in (15636, 15637):
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name=Enshrouded Server UDP {port}",
                "protocol=UDP",
                "dir=in",
                f"localport={port}",
                "action=allow",
                "enable=yes",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            success(f"Firewall rule added: UDP {port} inbound allowed.")
        else:
            warn(f"Could not add rule for port {port} — try running install.py as Administrator.")
            all_ok = False

    if not all_ok:
        print()
        print("  To add rules manually, run these in an Administrator Command Prompt:")
        for port in (15636, 15637):
            print(
                f'    netsh advfirewall firewall add rule name="Enshrouded Server UDP {port}" '
                f"protocol=UDP dir=in localport={port} action=allow enable=yes"
            )


# ---------------------------------------------------------------------------
# Port forwarding instructions
# ---------------------------------------------------------------------------
def print_port_info():
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "<your local IP>"

    print()
    print(f"{YELLOW}{'━' * 72}{NC}")
    print(f"{YELLOW}  IMPORTANT: Router Port Forwarding Required for Remote Players{NC}")
    print(f"{YELLOW}{'━' * 72}{NC}")
    print()
    print("  Players outside your local network can only connect if you forward")
    print("  these ports on your router to this machine:")
    print()
    print(f"    {CYAN}15636  UDP{NC}  — Game traffic")
    print(f"    {CYAN}15637  UDP{NC}  — Steam server query")
    print()
    print("  How to set up port forwarding:")
    print("    1. Log in to your router's admin page (usually http://192.168.1.1")
    print("       or http://192.168.0.1 — check your router's label).")
    print("    2. Navigate to 'Port Forwarding', 'Virtual Server', or 'NAT'.")
    print("    3. Add two UDP rules for ports 15636 and 15637, pointing to:")
    print(f"       {CYAN}{local_ip}{NC}  (this machine's current local IP)")
    print("    4. For a permanent setup, assign this machine a static local IP")
    print("       (DHCP reservation in your router) so the rules stay valid.")
    print()
    print(f"{YELLOW}{'━' * 72}{NC}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if sys.platform != "win32":
        die("This installer is for Windows only.\nOn Linux, run install.sh instead.")

    print()
    print(f"{CYAN}╔{'═' * 70}╗{NC}")
    print(f"{CYAN}║      Enshrouded Dedicated Server Manager — Windows Installer         ║{NC}")
    print(f"{CYAN}╚{'═' * 70}╝{NC}")
    print()

    check_prerequisites()
    choose_install_dir()
    create_dirs()
    install_steamcmd()
    download_server()
    setup_manager()
    setup_shortcuts()
    setup_firewall()
    print_port_info()

    print()
    success("Installation complete!")
    print()
    print(f"  To launch the server manager, double-click:")
    print(f"    {CYAN}{INSTALL_DIR / 'launch.bat'}{NC}")
    print()
    print("  Or use the desktop shortcut if you created one.")
    print()
    print("  On first launch, go to the Configuration tab to set your")
    print("  server name and password, then press Start on the Server tab.")
    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
