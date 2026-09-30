"""Sendet nach jedem Pipeline-Run automatisch eine E-Mail mit DATEV-CSV und Tages-Summary."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

def _cfg(key: str) -> str:
    try:
        from tools.settings_store import get
        return get(key)
    except Exception:
        return os.getenv(key.upper(), "")


def _build_html(run_result: dict, mandant_name: str | None) -> str:
    total       = run_result.get("belege", 0)
    exportiert  = run_result.get("exportiert", 0)
    rueckfragen = run_result.get("rueckfragen", 0)
    fehler      = run_result.get("fehler", 0)
    run_id      = run_result.get("run_id", "–")
    web_url     = _cfg("public_url").rstrip("/")
    rueckfragen_link = f"{web_url}/rueckfragen" if web_url else ""

    rows = ""
    if exportiert:
        rows += f"<tr><td>✓ Exportiert</td><td style='color:#2dd4a8;font-weight:600;'>{exportiert}</td></tr>"
    if rueckfragen:
        rows += f"<tr><td>⚠ Rückfragen offen</td><td style='color:#fbbf24;font-weight:600;'>{rueckfragen}</td></tr>"
    if fehler:
        rows += f"<tr><td>✗ Fehler</td><td style='color:#f87171;font-weight:600;'>{fehler}</td></tr>"
    rows += f"<tr><td>Belege gesamt</td><td>{total}</td></tr>"

    rueckfragen_section = ""
    if rueckfragen and rueckfragen_link:
        rueckfragen_section = f"""
        <p style='margin:16px 0 0;padding:12px 16px;background:#fef9c3;border-left:4px solid #fbbf24;border-radius:4px;font-size:13px;color:#92400e;'>
            ⚠ {rueckfragen} Beleg(e) erfordern manuelle Prüfung.<br>
            <a href='{rueckfragen_link}' style='color:#d97706;font-weight:600;'>→ Jetzt Rückfragen prüfen</a>
        </p>"""

    mandant_line = f"Mandant: <strong>{mandant_name}</strong> · " if mandant_name else ""

    return f"""<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'></head>
<body style='margin:0;padding:0;background:#f4f4f5;font-family:Inter,Helvetica,Arial,sans-serif;'>
<table width='100%' cellpadding='0' cellspacing='0' style='background:#f4f4f5;padding:32px 0;'>
<tr><td align='center'>
<table width='540' cellpadding='0' cellspacing='0' style='background:#0a1f1a;border-radius:16px;overflow:hidden;'>
  <tr><td style='padding:28px 32px 20px;border-bottom:1px solid rgba(167,243,208,0.1);'>
    <span style='font-size:18px;font-weight:800;color:#2dd4a8;letter-spacing:-0.03em;'>FiBu-Agent</span>
    <span style='font-size:11px;color:rgba(230,255,247,0.4);margin-left:8px;'>Tages-Report</span>
  </td></tr>
  <tr><td style='padding:24px 32px;'>
    <p style='margin:0 0 4px;font-size:13px;color:rgba(230,255,247,0.5);'>{mandant_line}Run-ID: {run_id}</p>
    <h1 style='margin:0 0 20px;font-size:22px;font-weight:600;color:#e6fff7;letter-spacing:-0.02em;'>Pipeline abgeschlossen</h1>
    <table cellpadding='0' cellspacing='0' style='width:100%;font-size:14px;'>
      <tr style='border-bottom:1px solid rgba(167,243,208,0.08);'>
        <th align='left' style='padding:6px 0;color:rgba(230,255,247,0.4);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;'>Ergebnis</th>
        <th align='left' style='padding:6px 0;color:rgba(230,255,247,0.4);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;'>Anzahl</th>
      </tr>
      {rows}
    </table>
    {rueckfragen_section}
    {'<p style="margin:20px 0 0;font-size:13px;color:rgba(230,255,247,0.5);">Die DATEV-CSV ist als Anhang beigefügt.</p>' if exportiert else '<p style="margin:20px 0 0;font-size:13px;color:rgba(230,255,247,0.4);">Keine exportierbaren Belege in diesem Lauf.</p>'}
  </td></tr>
  <tr><td style='padding:16px 32px;border-top:1px solid rgba(167,243,208,0.08);'>
    <p style='margin:0;font-size:11px;color:rgba(230,255,247,0.25);'>FiBu-Agent · KI-gestützte Buchhaltung · Powered by KI Automation Agency</p>
  </td></tr>
</table>
</td></tr></table></body></html>"""


def send_welcome(to_email: str, display_name: str, username: str,
                 password: str, login_url: str, plus_address: str) -> bool:
    """Sendet die Welcome-E-Mail an einen neu ongeboardeten Mandanten."""
    SMTP_HOST = _cfg("smtp_host") or "smtp.gmail.com"
    SMTP_PORT = int(_cfg("smtp_port") or "587")
    SMTP_USER = _cfg("imap_user")
    SMTP_PASS = _cfg("imap_password")
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("send_welcome: SMTP nicht konfiguriert — skip")
        return False

    subject = f"Ihr Zugang zum FiBu-Agent — Willkommen, {display_name}!"

    html = f"""<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'></head>
<body style='margin:0;padding:0;background:#f4f4f5;font-family:Inter,Helvetica,Arial,sans-serif;'>
<table width='100%' cellpadding='0' cellspacing='0' style='background:#f4f4f5;padding:32px 0;'>
<tr><td align='center'>
<table width='540' cellpadding='0' cellspacing='0' style='background:#0a1f1a;border-radius:16px;overflow:hidden;'>
  <tr><td style='padding:28px 32px 20px;border-bottom:1px solid rgba(167,243,208,0.1);'>
    <span style='font-size:18px;font-weight:800;color:#2dd4a8;letter-spacing:-0.03em;'>FiBu-Agent</span>
    <span style='font-size:11px;color:rgba(230,255,247,0.4);margin-left:8px;'>KI-Buchhaltung</span>
  </td></tr>
  <tr><td style='padding:28px 32px;'>
    <h1 style='margin:0 0 8px;font-size:22px;font-weight:600;color:#e6fff7;'>Willkommen, {display_name}!</h1>
    <p style='margin:0 0 24px;font-size:14px;color:rgba(230,255,247,0.6);'>Ihr FiBu-Agent-Zugang wurde eingerichtet. Hier sind Ihre Login-Daten:</p>

    <table cellpadding='0' cellspacing='0' style='width:100%;background:rgba(45,212,168,0.07);border:1px solid rgba(167,243,208,0.15);border-radius:10px;margin-bottom:24px;'>
      <tr><td style='padding:16px 20px;'>
        <p style='margin:0 0 10px;font-size:13px;color:rgba(230,255,247,0.5);'>Login-URL</p>
        <a href='{login_url}' style='font-size:15px;font-weight:600;color:#2dd4a8;text-decoration:none;'>{login_url}</a>
      </td></tr>
      <tr><td style='padding:0 20px 16px;border-top:1px solid rgba(167,243,208,0.08);padding-top:16px;'>
        <p style='margin:0 0 4px;font-size:12px;color:rgba(230,255,247,0.4);text-transform:uppercase;letter-spacing:0.05em;'>Benutzername</p>
        <p style='margin:0;font-size:15px;font-weight:600;color:#e6fff7;font-family:monospace;'>{username}</p>
      </td></tr>
      <tr><td style='padding:0 20px 16px;border-top:1px solid rgba(167,243,208,0.08);padding-top:16px;'>
        <p style='margin:0 0 4px;font-size:12px;color:rgba(230,255,247,0.4);text-transform:uppercase;letter-spacing:0.05em;'>Passwort (bitte nach erstem Login aendern)</p>
        <p style='margin:0;font-size:15px;font-weight:600;color:#e6fff7;font-family:monospace;'>{password}</p>
      </td></tr>
    </table>

    <table cellpadding='0' cellspacing='0' style='width:100%;background:rgba(45,212,168,0.07);border:1px solid rgba(167,243,208,0.15);border-radius:10px;margin-bottom:24px;'>
      <tr><td style='padding:16px 20px;'>
        <p style='margin:0 0 4px;font-size:12px;color:rgba(230,255,247,0.4);text-transform:uppercase;letter-spacing:0.05em;'>Ihre Beleg-E-Mail-Adresse</p>
        <p style='margin:4px 0 6px;font-size:17px;font-weight:700;color:#2dd4a8;font-family:monospace;'>{plus_address}</p>
        <p style='margin:0;font-size:12px;color:rgba(230,255,247,0.5);'>Senden Sie Ihre Rechnungen und Belege einfach als PDF-Anhang an diese Adresse. Der FiBu-Agent verarbeitet sie automatisch.</p>
      </td></tr>
    </table>

    <p style='margin:0;font-size:13px;color:rgba(230,255,247,0.4);'>Bei Fragen wenden Sie sich an Ihren Steuerberater oder antworten Sie auf diese E-Mail.</p>
  </td></tr>
  <tr><td style='padding:16px 32px;border-top:1px solid rgba(167,243,208,0.08);'>
    <p style='margin:0;font-size:11px;color:rgba(230,255,247,0.25);'>FiBu-Agent - KI-gestuetzte Buchhaltung - Powered by KI Automation Agency</p>
  </td></tr>
</table>
</td></tr></table></body></html>"""

    text = (
        f"Willkommen beim FiBu-Agent, {display_name}!\n\n"
        f"Login-URL:   {login_url}\n"
        f"Benutzername: {username}\n"
        f"Passwort:    {password}\n\n"
        f"Ihre Beleg-E-Mail: {plus_address}\n"
        f"Schicken Sie Rechnungen als PDF-Anhang an diese Adresse.\n\n"
        f"Bitte aendern Sie Ihr Passwort nach dem ersten Login."
    )

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"FiBu-Agent <{SMTP_USER}>"
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        logger.info("Welcome-E-Mail gesendet an %s", to_email)
        return True
    except Exception as exc:
        logger.exception("Welcome-E-Mail fehlgeschlagen: %s", exc)
        return False


def send_report(run_result: dict, export_path: Path | None = None,
                mandant_name: str | None = None, to_email: str | None = None) -> bool:
    """Sendet den Run-Report per E-Mail. Gibt True zurück wenn erfolgreich."""
    SMTP_HOST = _cfg("smtp_host") or "smtp.gmail.com"
    SMTP_PORT = int(_cfg("smtp_port") or "587")
    SMTP_USER = _cfg("imap_user")
    SMTP_PASS = _cfg("imap_password")
    recipient = to_email or _cfg("report_email_to") or SMTP_USER
    if not recipient or not SMTP_USER or not SMTP_PASS:
        logger.warning("report_email: SMTP nicht konfiguriert oder kein Empfänger — skip")
        return False

    total      = run_result.get("belege", 0)
    exportiert = run_result.get("exportiert", 0)
    rueck      = run_result.get("rueckfragen", 0)
    mandant_tag = f" [{mandant_name}]" if mandant_name else ""

    subject = f"FiBu-Agent{mandant_tag}: {exportiert}/{total} Belege exportiert"
    if rueck:
        subject += f" · {rueck} Rückfrage(n)"

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"FiBu-Agent <{SMTP_USER}>"
    msg["To"]      = recipient
    msg["Subject"] = subject

    text_body = (
        f"FiBu-Agent Tages-Report\n"
        f"{'Mandant: ' + mandant_name if mandant_name else ''}\n\n"
        f"Exportiert:  {exportiert}\n"
        f"Rückfragen:  {rueck}\n"
        f"Fehler:      {run_result.get('fehler', 0)}\n"
        f"Gesamt:      {total}\n\n"
        f"{'DATEV-CSV im Anhang.' if export_path else 'Keine exportierbaren Belege.'}"
    )
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(run_result, mandant_name), "html", "utf-8"))

    if export_path and Path(export_path).exists():
        with open(export_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="csv")
            att.add_header("Content-Disposition", "attachment",
                           filename=Path(export_path).name)
            msg.attach(att)

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipient, msg.as_string())
        server.quit()
        logger.info("Report-E-Mail gesendet an %s", recipient)
        return True
    except Exception as exc:
        logger.exception("Report-E-Mail fehlgeschlagen: %s", exc)
        return False
