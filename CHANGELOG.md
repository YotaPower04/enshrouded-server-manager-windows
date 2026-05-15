# Changelog

## [2.2.1] - 2026-05-15
- Dark-navy theme applied app-wide, matching the installer's palette (all tabs, inputs, lists, menus)
- Fast first-run setup: instead of waiting ~5 minutes for the server's first periodic autosave, the manager stops the server gracefully once its config file exists — the server flushes the generated world on shutdown — cutting first run to ~20–30s (gated by `FIRST_RUN_FAST`)
- Reworked the first-run overlay: a loading indicator during setup, with a *Restart Manager* confirmation button shown only once setup is complete
- Fixed the taskbar showing the Python icon — the manager now sets an explicit Windows AppUserModelID
- Fixed unreadable text on the Worlds tab (inactive list selection) and input fields that blended into the background
- Renamed the distributable from `Install.exe` to `Install ESM.exe`

## [2.2.0] - 2026-05-15
- Replaced the console installer (`install.py` / `install.bat`) with a Tkinter GUI installer (`install_tk.py`), shipped as `Install.exe`
- Fixed first-run save migration: clicking *Complete Setup Now* before the server's first periodic save no longer leaves `saves/worlds/world_1/` empty; the manager now waits for the save and migration auto-fires
- `stop_server()` and the first-run migration trigger now send Ctrl+C to the server via `AttachConsole` + `GenerateConsoleCtrlEvent`, so the server flushes its save on shutdown instead of being `TerminateProcess`ed
- Uncaught Python exceptions are now logged to `manager_error.log` next to the script (`pythonw.exe` previously swallowed every traceback)
- Fixed `OSError [WinError 6]` on Start by adding `stdin=subprocess.DEVNULL` to the Windows `taskkill` calls (pythonw has a NULL stdin, which broke `subprocess.run(capture_output=True, ...)`)
- New flat-style icons (`install.ico`, `manager.ico`, `running.ico`); installer copies `manager.ico` / `running.ico` next to the manager and points shortcuts at them
- Repo restructured into `src/`, `assets/`, `scripts/` with `Install.exe` at the root

## [2.1.0] - 2026-05-14
- Cross-platform Windows support: server now runs natively on Windows (no Wine/GE-Proton needed)
- Added `install.py` — Windows installer (downloads SteamCMD, Enshrouded server, creates venv, desktop shortcut, firewall rules)
- SteamCMD is now kept after installation (useful for manual server updates)

## [2.0.0] - 2026-05-09
- Initial community release
