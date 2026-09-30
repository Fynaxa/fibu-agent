"""
FiBu-Agent als macOS-Hintergrunddienst einrichten.

Ausführen:
  python install_service.py install     ← Dienst installieren & starten
  python install_service.py uninstall   ← Dienst entfernen
  python install_service.py restart     ← Dienst neu starten (nach Updates)
  python install_service.py status      ← Status anzeigen
  python install_service.py logs        ← Live-Logs anzeigen

Was passiert bei 'install':
  - Erstellt ~/Library/LaunchAgents/com.fibu-agent.plist
  - Startet den Dienst sofort
  - Ab jetzt: startet automatisch beim Mac-Login, neustart bei Absturz
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).parent.resolve()
VENV_PY    = ROOT / ".venv" / "bin" / "python"
PYTHON     = str(VENV_PY) if VENV_PY.exists() else sys.executable
START_PY   = ROOT / "start_public.py"
LOG_OUT    = ROOT / "logs" / "fibu-agent.log"
LOG_ERR    = ROOT / "logs" / "fibu-agent-error.log"
LABEL      = "com.fibu-agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

BOLD  = "\033[1m"
GREEN = "\033[32m"
YELLOW= "\033[33m"
RED   = "\033[31m"
DIM   = "\033[2m"
RESET = "\033[0m"


def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def err(msg):  print(f"  {RED}✗{RESET}  {msg}")


def _plist_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>{PYTHON}</string>
    <string>{START_PY}</string>
  </array>

  <key>WorkingDirectory</key>
  <string>{ROOT}</string>

  <!-- Automatisch neu starten bei Absturz -->
  <key>KeepAlive</key>
  <true/>

  <!-- Beim Login starten -->
  <key>RunAtLoad</key>
  <true/>

  <!-- Logs -->
  <key>StandardOutPath</key>
  <string>{LOG_OUT}</string>
  <key>StandardErrorPath</key>
  <string>{LOG_ERR}</string>

  <!-- Umgebungsvariablen -->
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
"""


def cmd(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def install():
    print(f"\n{BOLD}FiBu-Agent Dienst installieren{RESET}\n")

    # Logs-Verzeichnis
    LOG_OUT.parent.mkdir(exist_ok=True)
    ok(f"Log-Verzeichnis: {LOG_OUT.parent}")

    # Plist schreiben
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_content())
    ok(f"LaunchAgent: {PLIST_PATH}")

    # Laden (falls bereits geladen → erst entladen)
    cmd(["launchctl", "unload", str(PLIST_PATH)], check=False)
    result = cmd(["launchctl", "load", str(PLIST_PATH)], check=False)

    if result.returncode == 0:
        ok("Dienst geladen und gestartet.")
    else:
        warn(f"launchctl load: {result.stderr.strip() or 'kein Fehler-Output'}")

    print(f"""
  {GREEN}{BOLD}Fertig!{RESET}

  Der FiBu-Agent läuft jetzt im Hintergrund und startet
  automatisch beim nächsten Mac-Login neu.

  Nützliche Befehle:
  {DIM}python install_service.py status{RESET}   → Status prüfen
  {DIM}python install_service.py logs{RESET}     → Live-Logs
  {DIM}python install_service.py restart{RESET}  → Nach Updates neu starten
""")


def uninstall():
    print(f"\n{BOLD}FiBu-Agent Dienst entfernen{RESET}\n")

    if not PLIST_PATH.exists():
        warn("Kein LaunchAgent gefunden — bereits deinstalliert?")
        return

    cmd(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink()
    ok("LaunchAgent entfernt.")
    ok("Dienst gestoppt.")
    print()


def restart():
    print(f"\n{BOLD}FiBu-Agent neu starten{RESET}\n")

    if not PLIST_PATH.exists():
        err("Kein LaunchAgent gefunden. Erst installieren:")
        print(f"  python install_service.py install")
        return

    # Plist neu schreiben (falls Python-Pfad etc. geändert)
    PLIST_PATH.write_text(_plist_content())

    cmd(["launchctl", "unload", str(PLIST_PATH)], check=False)
    import time; time.sleep(1)
    result = cmd(["launchctl", "load", str(PLIST_PATH)], check=False)

    if result.returncode == 0:
        ok("Dienst neu gestartet.")
    else:
        err(f"Neustart fehlgeschlagen: {result.stderr.strip()}")
    print()


def status():
    print(f"\n{BOLD}FiBu-Agent Status{RESET}\n")

    if not PLIST_PATH.exists():
        warn("LaunchAgent nicht installiert.")
        print(f"  {DIM}python install_service.py install{RESET}")
        print()
        return

    result = cmd(["launchctl", "list", LABEL], check=False)
    if result.returncode != 0 or "Could not find service" in result.stdout:
        warn("Dienst installiert, aber nicht aktiv.")
    else:
        lines = result.stdout.strip().splitlines()
        pid_line = next((l for l in lines if '"PID"' in l or "PID" in l), "")
        running = "PID" in result.stdout and '"PID" = ' in result.stdout
        if running:
            ok("Dienst läuft.")
        else:
            warn("Dienst gestoppt (wird beim nächsten Login neu gestartet).")

    # Log-Tail
    if LOG_OUT.exists():
        print(f"\n  {DIM}Letzte Zeilen aus {LOG_OUT.name}:{RESET}")
        lines = LOG_OUT.read_text().splitlines()
        for line in lines[-8:]:
            print(f"  {DIM}{line}{RESET}")
    print()


def logs():
    print(f"\n{BOLD}Live-Logs (Strg+C zum Beenden){RESET}\n")
    if not LOG_OUT.exists():
        LOG_OUT.parent.mkdir(exist_ok=True)
        LOG_OUT.touch()
    try:
        subprocess.run(["tail", "-f", str(LOG_OUT)])
    except KeyboardInterrupt:
        print()


# ─── CLI ──────────────────────────────────────────────────

COMMANDS = {
    "install":   install,
    "uninstall": uninstall,
    "restart":   restart,
    "status":    status,
    "logs":      logs,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"\nVerwendung: python install_service.py [{'|'.join(COMMANDS)}]\n")
        for name, fn in COMMANDS.items():
            doc = (fn.__doc__ or "").strip().splitlines()[0]
            print(f"  {BOLD}{name:<12}{RESET} {DIM}{doc}{RESET}")
        print()
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
