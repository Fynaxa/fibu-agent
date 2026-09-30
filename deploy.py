"""
Deploy-Assistent: FiBu-Agent auf Hetzner VPS deployen.

Ausführen: python deploy.py

Voraussetzungen:
  - Hetzner-Server erstellt (Ubuntu 22.04, SSH-Key hinterlegt)
  - Server-IP zur Hand
  - Domain 'fibo-agent.com' bei Cloudflare (DNS-Eintrag wird am Ende erklärt)

Was passiert:
  1. SSH-Verbindung prüfen
  2. Server-Abhängigkeiten installieren (Python, Tesseract, Poppler)
  3. Projektdateien übertragen (rsync)
  4. Python-Umgebung auf Server einrichten (venv + pip)
  5. systemd-Service einrichten (automatischer Start, Neustart bei Absturz)
  6. Cloudflare DNS-Anweisungen anzeigen
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.resolve()
ENV_FILE = ROOT / ".env"

BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def err(msg):   print(f"  {RED}✗{RESET}  {msg}")
def step(n, t): print(f"\n{BOLD}Schritt {n}  –  {t}{RESET}\n")
def ask(prompt, default=""):
    hint = f" [{default}]" if default else ""
    val  = input(f"  {BOLD}{prompt}{RESET}{DIM}{hint}{RESET}: ").strip()
    return val or default


def ssh(host: str, user: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Führt einen Befehl per SSH aus."""
    full = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"{user}@{host}", cmd]
    return subprocess.run(full, check=check, text=True, capture_output=False)


def scp(host: str, user: str, local: str, remote: str):
    """Kopiert eine Datei per SCP."""
    subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no",
         local, f"{user}@{host}:{remote}"],
        check=True
    )


def rsync(host: str, user: str, local_dir: str, remote_dir: str):
    """Überträgt Projektdateien per rsync."""
    subprocess.run([
        "rsync", "-avz", "--progress",
        "--exclude=.venv/",
        "--exclude=.git/",
        "--exclude=logs/",
        "--exclude=__pycache__/",
        "--exclude=*.pyc",
        "--exclude=*.db",
        "--exclude=inbox/*",
        "--exclude=outbox/*",
        "--exclude=archiv/*",
        "--exclude=demo/*.pdf",
        "--exclude=cloudflared.yml",
        "--filter=:- .gitignore",
        f"{local_dir}/",
        f"{user}@{host}:{remote_dir}/",
    ], check=True)


# ─── Hauptprogramm ────────────────────────────────────────

def main():
    print(f"""
{BOLD}{'═'*60}
  FiBu-Agent  –  Deploy-Assistent
{'═'*60}{RESET}

  Dieser Assistent richtet deinen Hetzner-Server ein und
  deployt den FiBu-Agent vollautomatisch.

  {DIM}Noch keinen Server? → https://console.hetzner.cloud
  Empfehlung: CX22 (4 GB RAM) · Ubuntu 22.04 · SSH-Key{RESET}
""")

    # ── Server-Daten abfragen ──────────────────────────────
    server_ip = ask("Server-IP (aus Hetzner-Dashboard)")
    if not server_ip:
        err("Keine IP angegeben. Abbruch.")
        sys.exit(1)

    server_user  = ask("SSH-Benutzer", "root")
    domain       = ask("Deine Domain (z.B. app.fibo-agent.com)", "app.fibo-agent.com")
    public_url   = f"https://{domain}"
    deploy_dir   = ask("Installationsverzeichnis auf Server", "/opt/fibu-agent")
    flask_port   = ask("Flask-Port", "5001")

    print()

    # ── 1. SSH-Verbindung testen ───────────────────────────
    step(1, "SSH-Verbindung testen")
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
         f"{server_user}@{server_ip}", "echo OK"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or "OK" not in result.stdout:
        err(f"SSH-Verbindung fehlgeschlagen.")
        print(f"\n  Bitte prüfen:")
        print(f"  1. Server-IP korrekt?  ({server_ip})")
        print(f"  2. SSH-Key im Hetzner-Dashboard hinterlegt?")
        print(f"  3. Server läuft? (im Hetzner-Dashboard prüfen)")
        print(f"\n  Test manuell: {DIM}ssh {server_user}@{server_ip}{RESET}")
        sys.exit(1)
    ok(f"Verbunden mit {server_user}@{server_ip}")

    # ── 2. System-Abhängigkeiten installieren ──────────────
    step(2, "System-Abhängigkeiten installieren")
    print(f"  {DIM}Installiere Python, Tesseract, Poppler … (ca. 1-2 Min.){RESET}\n")

    setup_cmds = " && ".join([
        "apt-get update -q",
        "apt-get install -y -q python3.11 python3.11-venv python3-pip",
        "apt-get install -y -q tesseract-ocr tesseract-ocr-deu",
        "apt-get install -y -q poppler-utils libgl1 libglib2.0-0",
        "apt-get install -y -q rsync curl",
        f"mkdir -p {deploy_dir}",
        f"mkdir -p {deploy_dir}/logs",
        f"mkdir -p {deploy_dir}/inbox {deploy_dir}/outbox {deploy_dir}/archiv",
    ])
    ssh(server_ip, server_user, setup_cmds)
    ok("System-Pakete installiert.")

    # ── 3. Projektdateien übertragen ──────────────────────
    step(3, "Projektdateien übertragen (rsync)")
    rsync(server_ip, server_user, str(ROOT), deploy_dir)
    ok("Dateien übertragen.")

    # ── 4. .env auf Server anpassen und übertragen ─────────
    step(4, ".env für Server konfigurieren")

    env_lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []

    def _set(lines, key, value):
        for i, l in enumerate(lines):
            if l.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                return lines
        lines.append(f"{key}={value}")
        return lines

    env_lines = _set(env_lines, "PUBLIC_URL",  public_url)
    env_lines = _set(env_lines, "FLASK_PORT",  flask_port)

    # Cloudflare- und ngrok-Tunnel auf Server deaktivieren
    env_lines = [
        l if not l.strip().startswith("CLOUDFLARE_TUNNEL_NAME=") else f"# {l}"
        for l in env_lines
    ]
    env_lines = [
        l if not l.strip().startswith("NGROK_AUTHTOKEN=") else f"# {l}"
        for l in env_lines
    ]

    server_env = "\n".join(env_lines) + "\n"
    server_env_path = ROOT / ".env.server"
    server_env_path.write_text(server_env)

    scp(server_ip, server_user, str(server_env_path), f"{deploy_dir}/.env")
    server_env_path.unlink()

    # Berechtigungen einschränken (nur root kann lesen)
    ssh(server_ip, server_user, f"chmod 600 {deploy_dir}/.env")
    ok(".env auf Server übertragen (chmod 600).")

    # ── 5. Python-Umgebung einrichten ─────────────────────
    step(5, "Python-Umgebung einrichten")

    venv_cmds = " && ".join([
        f"cd {deploy_dir}",
        "python3.11 -m venv .venv",
        ".venv/bin/pip install --upgrade pip -q",
        ".venv/bin/pip install -r requirements.txt -q",
    ])
    ssh(server_ip, server_user, venv_cmds)
    ok("Python-Umgebung und Pakete installiert.")

    # ── 6. systemd-Service einrichten ─────────────────────
    step(6, "systemd-Service einrichten")

    service_content = f"""[Unit]
Description=FiBu-Agent KI-Buchhaltung
After=network.target

[Service]
Type=simple
WorkingDirectory={deploy_dir}
ExecStart={deploy_dir}/.venv/bin/python {deploy_dir}/start_server.py
Restart=always
RestartSec=5
StandardOutput=append:{deploy_dir}/logs/fibu-agent.log
StandardError=append:{deploy_dir}/logs/fibu-agent-error.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""

    # Service-Datei auf Server schreiben
    escaped = service_content.replace("'", "'\\''")
    ssh(server_ip, server_user,
        f"cat > /etc/systemd/system/fibu-agent.service << 'SVCEOF'\n{service_content}SVCEOF")

    # Aktivieren und starten
    ssh(server_ip, server_user,
        "systemctl daemon-reload && systemctl enable fibu-agent && systemctl restart fibu-agent")
    ok("systemd-Service aktiviert und gestartet.")

    # ── 7. Status prüfen ──────────────────────────────────
    step(7, "Service-Status prüfen")
    import time
    time.sleep(3)
    ssh(server_ip, server_user, "systemctl status fibu-agent --no-pager -l", check=False)

    # ── Abschluss + DNS-Anweisungen ───────────────────────
    print(f"""
{BOLD}{'═'*60}
  {GREEN}Deploy erfolgreich!{RESET}{BOLD}
{'═'*60}{RESET}

  FiBu-Agent läuft auf: {BOLD}http://{server_ip}:{flask_port}{RESET}

  {BOLD}Letzter Schritt: Cloudflare DNS einrichten{RESET}
  {DIM}(damit https://{domain} funktioniert){RESET}

  1. Öffne: https://dash.cloudflare.com
  2. Wähle deine Domain → DNS → Records
  3. Klick "Add record":

     Typ:    A
     Name:   {domain.split('.')[0]}   (z.B. "app")
     IPv4:   {server_ip}
     Proxy:  ✓ (oranges Wolken-Symbol = Cloudflare-Proxy an)

  4. Speichern → nach 1-2 Min. erreichbar unter:
     {BOLD}https://{domain}{RESET}

  {BOLD}Nützliche Server-Befehle:{RESET}
  {DIM}# Logs live verfolgen:
  ssh {server_user}@{server_ip} "journalctl -u fibu-agent -f"

  # Service neu starten (nach Updates):
  python deploy.py   ← erneut ausführen

  # Direkt auf Server einloggen:
  ssh {server_user}@{server_ip}{RESET}
{'═'*60}
""")


if __name__ == "__main__":
    main()
