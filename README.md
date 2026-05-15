# Enshrouded Server Manager — Windows Edition

A PyQt6 desktop app for managing a dedicated Enshrouded server on Windows. The server runs natively (no Wine / Proton), with a system tray icon and a tabbed GUI for everything you need.

For the Linux version (which runs the Windows server binary through GE-Proton), see [enshrouded-server-manager](https://github.com/YotaPower04/enshrouded-server-manager).

## Features

- **Server tab** — Start / stop / restart the server, see live status and uptime
- **Logs tab** — Live tail of the server log
- **Worlds tab** — Manage multiple save worlds, import existing saves, set nicknames
- **Resource Server tab** — Optional scheduled restart with snapshot-world rotation
- **Configuration tab** — Edit server name, passwords, player slots, gameplay settings
- System tray icon with quick controls (start / stop / open)
- First-run setup wizard — auto-generates the world and migrates saves to a managed layout
- Port-conflict detection on startup
- Graceful Ctrl+C shutdown so the server flushes its save on stop

## Requirements

- Windows 10 or 11 (x64)
- Internet connection — the installer downloads SteamCMD and the dedicated server (~5 GB)
- The installer auto-installs Python 3.12 and the Visual C++ 2022 x64 Redistributable if either is missing

## Installation

Download `Install ESM.exe` from the [Releases page](https://github.com/YotaPower04/enshrouded-server-manager-windows/releases) and run it. The GUI installer will:

1. Verify (and install if missing) Python 3.12 and VC++ Redistributable 2022 x64
2. Download SteamCMD and the Enshrouded dedicated server
3. Create a venv with PyQt6
4. Write `launch.bat` and optional desktop / Start Menu / Startup shortcuts
5. Optionally add Windows Firewall rules for UDP 15636 + 15637

After install, launch the manager via the desktop shortcut, Start Menu entry, or `launch.bat` inside your install directory.

## Port Forwarding

For players outside your local network to connect, forward these ports on your router:

| Port  | Protocol | Purpose            |
|-------|----------|--------------------|
| 15636 | UDP      | Game traffic       |
| 15637 | UDP      | Steam server query |

The installer can add inbound Windows Firewall rules for both ports automatically.

## First Run

On first launch the manager auto-starts the server to generate the world. After ~5 minutes the server writes its first periodic save to disk; once that lands the manager migrates the save files into a managed layout (`saves/worlds/world_1/`) and restarts. Normal operation begins after that.

Clicking **Complete Setup Now** before the first save lands will simply show a "waiting for first save" message — the manager won't kill the server prematurely.

## Building from source

```cmd
scripts\build.bat
```

Requires Python 3.12 with Pillow + PyInstaller on `PATH`. Produces `Install ESM.exe` in the repo root.

## License

MIT — see [LICENSE](LICENSE).
