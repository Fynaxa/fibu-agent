"""FiBu-Agent Web-UI: Dashboard, Upload, Rückfragen, DATEV-Download."""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import Thread

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, jsonify, session, g)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

# Projekt-Root setzen, bevor config geladen wird
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.config import (ROOT, OUTBOX_DIR, load_mandanten, get_mandant, mandant_dirs,
                          INBOX_DIR, add_mandant, update_mandant, delete_mandant)
from tools import audit_log
from tools.auth import authenticate, get_user, ensure_admin_exists, init_auth_tables

logger = logging.getLogger(__name__)

app = Flask(__name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# CSRF-Schutz
csrf = CSRFProtect(app)

# Rate-Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)

# Auth-Tabellen und Admin anlegen
init_auth_tables()
ensure_admin_exists()


# ─── Auth Middleware ──────────────────────────────────────

def login_required(f):
    """Decorator: Route erfordert Login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Bitte einloggen.", "error")
            return redirect(url_for("login", next=request.path))
        g.user = get_user(session["user_id"])
        if not g.user:
            session.clear()
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: Route erfordert Admin-Rolle."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        g.user = get_user(session["user_id"])
        if not g.user or g.user["role"] != "admin":
            flash("Admin-Rechte erforderlich.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_user():
    """Macht den aktuellen User in allen Templates verfügbar."""
    user = None
    if "user_id" in session:
        user = get_user(session["user_id"])
    return {"current_user": user}


# ─── Hilfsfunktionen ─────────────────────────────────────

def _load_runs(outbox: Path) -> list[dict]:
    """Lädt alle Run-Snapshots aus einem outbox-Verzeichnis."""
    runs = []
    for f in sorted(outbox.rglob("run_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = str(f)
            runs.append(data)
        except Exception:
            pass
    return runs


def _load_all_belege(outbox: Path) -> list[dict]:
    """Sammelt alle Belege aus allen Runs."""
    belege = []
    for run in _load_runs(outbox):
        for b in run.get("belege", []):
            b["_run_id"] = run.get("run_id", "?")
            belege.append(b)
    return belege


# ─── Auth Routes ──────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = authenticate(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True
            next_url = request.args.get("next", url_for("dashboard"))
            return redirect(next_url)
        else:
            flash("Ungültige Zugangsdaten.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Erfolgreich abgemeldet.", "success")
    return redirect(url_for("login"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Passwort ändern."""
    if request.method == "POST":
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if len(new_pw) < 8:
            flash("Passwort muss mindestens 8 Zeichen lang sein.", "error")
        elif new_pw != confirm:
            flash("Passwörter stimmen nicht überein.", "error")
        else:
            from tools.auth import change_password
            change_password(g.user["id"], new_pw)
            flash("Passwort geändert.", "success")
            return redirect(url_for("settings"))
    return render_template("settings.html")


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    """Benutzerverwaltung (nur Admin)."""
    from tools.auth import create_user, list_users, deactivate_user

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            display_name = request.form.get("display_name", "").strip()
            role = request.form.get("role", "user")
            mandant_ids = request.form.getlist("mandant_ids")

            if not username or not password:
                flash("Benutzername und Passwort sind Pflichtfelder.", "error")
            elif len(password) < 8:
                flash("Passwort muss mindestens 8 Zeichen lang sein.", "error")
            elif create_user(username, password, display_name, role, mandant_ids):
                flash(f"Benutzer '{username}' erstellt.", "success")
            else:
                flash(f"Benutzer '{username}' konnte nicht erstellt werden (existiert bereits?).", "error")

        elif action == "deactivate":
            user_id = int(request.form.get("user_id", 0))
            if user_id == g.user["id"]:
                flash("Du kannst dich nicht selbst deaktivieren.", "error")
            else:
                deactivate_user(user_id)
                flash("Benutzer deaktiviert.", "success")

    users = list_users()
    mandanten = load_mandanten()
    return render_template("admin_users.html", users=users, mandanten=mandanten)


# ─── Mandanten-Verwaltung ─────────────────────────────────

@app.route("/admin/mandanten", methods=["GET", "POST"])
@admin_required
def admin_mandanten():
    """Mandanten anlegen, bearbeiten, löschen."""
    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            mandant_id = request.form.get("id", "").strip().upper()
            name = request.form.get("name", "").strip()
            kontenrahmen = request.form.get("kontenrahmen", "SKR03")
            berater_nr = request.form.get("berater_nr", "").strip()
            mandant_nr = request.form.get("mandant_nr", "").strip()
            notizen = request.form.get("notizen", "").strip()

            if not mandant_id or not name:
                flash("Mandanten-ID und Name sind Pflichtfelder.", "error")
            elif not mandant_id.replace("-", "").replace("_", "").isalnum():
                flash("Mandanten-ID darf nur Buchstaben, Zahlen, - und _ enthalten.", "error")
            else:
                mandant = {
                    "id": mandant_id,
                    "name": name,
                    "kontenrahmen": kontenrahmen,
                    "berater_nr": berater_nr,
                    "mandant_nr": mandant_nr,
                    "inbox": f"inbox/{mandant_id}",
                    "outbox": f"outbox/{mandant_id}",
                    "archiv": f"archiv/{mandant_id}",
                    "eigene_regeln": [],
                    "notizen": notizen,
                }
                if add_mandant(mandant):
                    # Verzeichnisse sofort anlegen
                    mandant_dirs(mandant)
                    flash(f"Mandant '{name}' ({mandant_id}) angelegt.", "success")
                else:
                    flash(f"Mandant mit ID '{mandant_id}' existiert bereits.", "error")

        elif action == "update":
            mandant_id = request.form.get("mandant_id", "")
            updates = {
                "name": request.form.get("name", "").strip(),
                "kontenrahmen": request.form.get("kontenrahmen", "SKR03"),
                "berater_nr": request.form.get("berater_nr", "").strip(),
                "mandant_nr": request.form.get("mandant_nr", "").strip(),
                "notizen": request.form.get("notizen", "").strip(),
            }
            # Leere Werte nicht überschreiben
            updates = {k: v for k, v in updates.items() if v}
            if update_mandant(mandant_id, updates):
                flash(f"Mandant '{mandant_id}' aktualisiert.", "success")
            else:
                flash(f"Mandant '{mandant_id}' nicht gefunden.", "error")

        elif action == "delete":
            mandant_id = request.form.get("mandant_id", "")
            if delete_mandant(mandant_id):
                flash(f"Mandant '{mandant_id}' entfernt.", "success")
            else:
                flash(f"Mandant '{mandant_id}' nicht gefunden.", "error")

    mandanten = load_mandanten()
    return render_template("admin_mandanten.html", mandanten=mandanten)


# ─── App Routes ───────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    mandanten = load_mandanten()

    # Mandantenzugriff einschränken für Nicht-Admins
    if g.user["role"] != "admin" and g.user["mandant_ids"]:
        mandanten = [m for m in mandanten if m["id"] in g.user["mandant_ids"]]

    from tools.db import get_belege as _db_belege
    allowed_ids = [m["id"] for m in mandanten]
    all_belege = []
    for mid in allowed_ids:
        all_belege.extend(_db_belege(mandant_id=mid))

    total = len(all_belege)
    exportiert = sum(1 for b in all_belege if b.get("status") == "exportiert")
    rueckfragen = [b for b in all_belege if b.get("status") == "rueckfrage"]
    fehler = sum(1 for b in all_belege if b.get("status") == "fehler")

    # Anzahl Belege in allen Inbox-Verzeichnissen (für Onboarding-Hinweis)
    inbox_count = 0
    for m in mandanten:
        dirs = mandant_dirs(m)
        try:
            inbox_count += sum(1 for f in dirs["inbox"].iterdir()
                               if f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"))
        except Exception:
            pass

    return render_template("dashboard.html",
                           mandanten=mandanten,
                           total=total,
                           exportiert=exportiert,
                           rueckfragen=rueckfragen,
                           fehler=fehler,
                           inbox_count=inbox_count)


@app.route("/mandant/<mandant_id>")
@login_required
def mandant_detail(mandant_id):
    # Zugriffsprüfung
    if g.user["role"] != "admin" and g.user["mandant_ids"] and mandant_id not in g.user["mandant_ids"]:
        flash("Kein Zugriff auf diesen Mandanten.", "error")
        return redirect(url_for("dashboard"))

    m = get_mandant(mandant_id)
    if not m:
        flash(f"Mandant {mandant_id} nicht gefunden", "error")
        return redirect(url_for("dashboard"))
    dirs = mandant_dirs(m)
    belege = _load_all_belege(dirs["outbox"])
    exports = sorted(dirs["outbox"].glob("EXTF_*.csv"), reverse=True)
    from tools.config import IMAP_USER
    if IMAP_USER and "@" in IMAP_USER:
        local, domain = IMAP_USER.split("@", 1)
        inbox_email = f"{local}+{mandant_id.lower()}@{domain}"
    else:
        inbox_email = None
    return render_template("mandant.html", mandant=m, belege=belege, exports=exports,
                           root=ROOT, inbox_email=inbox_email)


@app.route("/upload", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def upload():
    mandanten = load_mandanten()
    if g.user["role"] != "admin" and g.user["mandant_ids"]:
        mandanten = [m for m in mandanten if m["id"] in g.user["mandant_ids"]]

    if request.method == "POST":
        mandant_id = request.form.get("mandant_id")
        files = request.files.getlist("belege")
        if not files or not any(f.filename for f in files):
            flash("Keine Dateien ausgewählt", "error")
            return redirect(url_for("upload"))

        # Zielordner bestimmen
        if mandant_id:
            m = get_mandant(mandant_id)
            if not m:
                flash(f"Mandant {mandant_id} nicht gefunden", "error")
                return redirect(url_for("upload"))
            target = mandant_dirs(m)["inbox"]
        else:
            target = INBOX_DIR
        target.mkdir(parents=True, exist_ok=True)

        # Dateityp-Prüfung
        ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
        saved = 0
        for f in files:
            if f.filename:
                ext = Path(f.filename).suffix.lower()
                if ext not in ALLOWED:
                    flash(f"'{f.filename}' übersprungen — nur PDF/Bild erlaubt", "error")
                    continue
                # Sicherer Dateiname
                from werkzeug.utils import secure_filename
                safe_name = secure_filename(f.filename)
                if not safe_name:
                    continue
                dest = target / safe_name
                f.save(str(dest))
                saved += 1

        if saved:
            flash(f"{saved} Beleg(e) hochgeladen nach {mandant_id or 'global'}", "success")
        return redirect(url_for("upload"))

    return render_template("upload.html", mandanten=mandanten)


@app.route("/run", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def run_pipeline():
    """Startet einen Pipeline-Run (im Hintergrund)."""
    mandant_id = request.form.get("mandant_id") or None

    def _run():
        from agents.fibu_agent import run
        try:
            run(mandant_id=mandant_id)
        except Exception as exc:
            logger.exception("Pipeline-Run fehlgeschlagen: %s", exc)

    thread = Thread(target=_run, daemon=True)
    thread.start()
    flash(f"Pipeline gestartet für {mandant_id or 'alle'}. Ergebnis erscheint in wenigen Sekunden.", "success")
    return redirect(url_for("dashboard"))


@app.route("/multi-entity")
@login_required
def multi_entity():
    """Mandantenübergreifende Inbox — alle Belege aller Entities in einer Ansicht."""
    mandanten = load_mandanten()
    if g.user["role"] != "admin" and g.user["mandant_ids"]:
        mandanten = [m for m in mandanten if m["id"] in g.user["mandant_ids"]]

    from tools.db import get_belege as _db_belege
    mandant_map = {m["id"]: m["name"] for m in mandanten}
    allowed_ids = list(mandant_map.keys())

    alle_belege = []
    for mid in allowed_ids:
        for b in _db_belege(mandant_id=mid):
            b["_mandant_id"] = mid
            b["_mandant_name"] = mandant_map[mid]
            alle_belege.append(b)

    alle_belege.sort(key=lambda b: b.get("belegdatum", ""), reverse=True)

    total      = len(alle_belege)
    exportiert = sum(1 for b in alle_belege if b.get("status") == "exportiert")
    rueckfr    = [b for b in alle_belege if b.get("status") == "rueckfrage"]
    fehler     = sum(1 for b in alle_belege if b.get("status") == "fehler")
    offen      = sum(1 for b in alle_belege if b.get("status") in ("neu", "kontiert"))

    mandant_stats = []
    for m in mandanten:
        mb = [b for b in alle_belege if b.get("_mandant_id") == m["id"]]
        mandant_stats.append({
            "id": m["id"],
            "name": m["name"],
            "total": len(mb),
            "exportiert": sum(1 for b in mb if b.get("status") == "exportiert"),
            "rueckfragen": sum(1 for b in mb if b.get("status") == "rueckfrage"),
            "fehler": sum(1 for b in mb if b.get("status") == "fehler"),
            "offen": sum(1 for b in mb if b.get("status") in ("neu", "kontiert")),
        })

    return render_template("multi_entity.html",
                           mandanten=mandanten,
                           alle_belege=alle_belege,
                           mandant_stats=mandant_stats,
                           total=total,
                           exportiert=exportiert,
                           rueckfragen=rueckfr,
                           fehler=fehler,
                           offen=offen)


@app.route("/rueckfragen")
@login_required
def rueckfragen():
    """Zeigt alle offenen Rückfragen — aus SQLite (Echtzeit-Quelle)."""
    from tools.db import get_belege
    belege = get_belege(status="rueckfrage")
    # Zugriffsbeschränkung für Nicht-Admins
    if g.user["role"] != "admin" and g.user["mandant_ids"]:
        belege = [b for b in belege if b.get("mandant_id") in g.user["mandant_ids"]]
    return render_template("rueckfragen.html", belege=belege)


@app.route("/beleg/<beleg_id>")
@login_required
def beleg_detail(beleg_id):
    """Zeigt Details zu einem einzelnen Beleg — inkl. Kontierungsformular."""
    from tools.db import get_beleg
    from tools import audit_log as al
    beleg = get_beleg(beleg_id)
    if not beleg:
        flash("Beleg nicht gefunden.", "error")
        return redirect(url_for("rueckfragen"))
    # Zugriffsprüfung
    if g.user["role"] != "admin" and g.user["mandant_ids"]:
        if beleg.get("mandant_id") and beleg["mandant_id"] not in g.user["mandant_ids"]:
            flash("Kein Zugriff auf diesen Beleg.", "error")
            return redirect(url_for("rueckfragen"))
    history = al.get_history(beleg_id)
    return render_template("beleg_detail.html", beleg=beleg, history=history)


@app.route("/beleg/<beleg_id>/resolve", methods=["POST"])
@login_required
def beleg_resolve(beleg_id):
    """Löst eine Rückfrage auf: Korrektur speichern + Status auf validiert setzen."""
    from tools.db import get_beleg, upsert_beleg, save_kontierung_korrektur, update_vendor_cache
    from tools import audit_log as al
    from tools.kontierung import auto_regelwerk_aktualisieren

    beleg = get_beleg(beleg_id)
    if not beleg:
        flash("Beleg nicht gefunden.", "error")
        return redirect(url_for("rueckfragen"))

    action = request.form.get("action", "approve")

    if action == "reject":
        upsert_beleg({**beleg, "status": "fehler", "rueckfrage_grund": "Manuell abgelehnt"})
        al.log_event(beleg_id, "manuell_abgelehnt", {"user": g.user["username"]})
        flash(f"Beleg {beleg_id} als Fehler markiert.", "success")
        return redirect(url_for("rueckfragen"))

    # Korrektur-Felder aus Formular
    soll_konto     = request.form.get("soll_konto", "").strip()
    haben_konto    = request.form.get("haben_konto", "1200").strip()
    steuerschluessel = request.form.get("steuerschluessel", "").strip()
    buchungstext   = request.form.get("buchungstext", "").strip()

    if not soll_konto:
        flash("Soll-Konto darf nicht leer sein.", "error")
        return redirect(url_for("beleg_detail", beleg_id=beleg_id))

    altes_konto = beleg.get("soll_konto", "")

    # Beleg aktualisieren und auf validiert setzen
    updated = {
        **beleg,
        "soll_konto":       soll_konto,
        "haben_konto":      haben_konto or "1200",
        "steuerschluessel": steuerschluessel,
        "buchungstext":     buchungstext or beleg.get("buchungstext", ""),
        "status":           "validiert",
        "rueckfrage_grund": None,
        "kontierung_methode": "manuell",
    }
    upsert_beleg(updated)

    al.log_event(beleg_id, "manuell_genehmigt", {
        "user": g.user["username"],
        "altes_konto": altes_konto,
        "neues_konto": soll_konto,
    })

    # Feedback-Loop: Vendor-Cache immer aktualisieren (Bestätigung oder Korrektur)
    ist_korrektur = bool(altes_konto and altes_konto != soll_konto)
    _lieferant = (beleg.get("lieferant") or "").strip()
    try:
        if not _lieferant:
            raise ValueError("Kein Lieferant — Vendor-Cache-Update übersprungen")
        update_vendor_cache(
            lieferant        = _lieferant,
            soll_konto       = soll_konto,
            bezeichnung      = buchungstext or beleg.get("buchungstext", ""),
            steuerschluessel = steuerschluessel or beleg.get("steuerschluessel", ""),
            mandant_id       = beleg.get("mandant_id"),
            bestaetigt       = not ist_korrektur,
        )
        if ist_korrektur:
            save_kontierung_korrektur(
                lieferant        = _lieferant,
                verwendungszweck = beleg.get("buchungstext") or beleg.get("verwendungszweck", ""),
                falsches_konto   = altes_konto,
                korrektes_konto  = soll_konto,
                mandant_id       = beleg.get("mandant_id"),
            )
        # Auto-Regelwerk: bei >= 3 Bestätigungen → Pattern in Regeldatei schreiben
        neue = auto_regelwerk_aktualisieren()
        if neue > 0:
            logger.info("Auto-Regelwerk: %d neue Pattern nach manueller Auflösung", neue)
    except Exception as exc:
        logger.warning("Feedback-Loop fehlgeschlagen (non-critical): %s", exc)

    flash(f"Beleg {beleg_id} genehmigt. Konto: {soll_konto}", "success")
    return redirect(url_for("rueckfragen"))


@app.route("/audit/<beleg_id>")
@login_required
def audit_detail(beleg_id):
    history = audit_log.get_history(beleg_id)
    verification = audit_log.verify_log(beleg_id)
    return render_template("audit.html", beleg_id=beleg_id, history=history, verification=verification)


@app.route("/api/pipeline-status")
@login_required
def pipeline_status_api():
    """Live-Status laufender Pipelines."""
    from tools.pipeline_status import get_status, get_active_runs
    run_id = request.args.get("run_id")
    if run_id:
        return jsonify(get_status(run_id))
    active = get_active_runs()
    all_recent = get_status()
    return jsonify({"active": active, "recent": all_recent})


@app.route("/costs")
@login_required
def costs():
    """API-Kosten-Übersicht."""
    from tools.cost_tracker import get_costs
    daily = get_costs("today")
    monthly = get_costs("month")
    return jsonify({"daily": daily, "monthly": monthly})


@app.route("/validate/<path:filepath>")
@login_required
def validate_export(filepath):
    """Validiert eine DATEV-CSV und gibt das Ergebnis als JSON zurück."""
    from tools.datev_validate import validate_datev_csv
    full = ROOT / filepath
    if not full.exists():
        return jsonify({"valid": False, "fehler": ["Datei nicht gefunden"]}), 404
    result = validate_datev_csv(full)
    return jsonify(result)


@app.route("/download/<path:filepath>")
@login_required
def download_file(filepath):
    full = ROOT / filepath
    if full.exists() and full.is_file():
        return send_file(str(full), as_attachment=True)
    flash("Datei nicht gefunden", "error")
    return redirect(url_for("dashboard"))


# ─── Vapi Voice-Agent API ────────────────────────────────
# Endpunkte für den KI-Telefonagenten (kein Browser-Login,
# stattdessen Token-Auth über X-Vapi-Secret Header)

def _vapi_auth() -> bool:
    """Prüft den Vapi-Secret-Token."""
    from tools.settings_store import get
    secret = get("vapi_secret")
    if not secret:
        return True  # Noch nicht konfiguriert → offen lassen
    return request.headers.get("X-Vapi-Secret") == secret


@app.route("/api/vapi/pipeline-status")
def vapi_pipeline_status():
    """Letzter Pipeline-Run eines Mandanten — für Vapi Tool Call."""
    if not _vapi_auth():
        return jsonify({"error": "Unauthorized"}), 401

    mandant_id = request.args.get("mandant_id", "").upper()
    if mandant_id:
        m = get_mandant(mandant_id)
        if not m:
            return jsonify({"gefunden": False, "nachricht": f"Mandant {mandant_id} nicht gefunden."})
        dirs = mandant_dirs(m)
        runs = _load_runs(dirs["outbox"])
    else:
        runs = _load_runs(OUTBOX_DIR)

    if not runs:
        return jsonify({
            "gefunden": False,
            "nachricht": "Es wurden noch keine Pipelines ausgeführt."
        })

    letzter = runs[0]
    return jsonify({
        "gefunden":      True,
        "run_id":        letzter.get("run_id", "–"),
        "datum":         letzter.get("datum", "–"),
        "uhrzeit":       letzter.get("uhrzeit", "–"),
        "belege":        letzter.get("belege", 0),
        "exportiert":    letzter.get("exportiert", 0),
        "rueckfragen":   letzter.get("rueckfragen", 0),
        "fehler":        letzter.get("fehler", 0),
        "nachricht": (
            f"Die Pipeline lief zuletzt am {letzter.get('datum','?')} "
            f"um {letzter.get('uhrzeit','?')} Uhr. "
            f"{letzter.get('belege',0)} Belege verarbeitet, "
            f"{letzter.get('exportiert',0)} exportiert"
            + (f", {letzter.get('rueckfragen',0)} Rückfrage(n) offen" if letzter.get('rueckfragen') else "")
            + "."
        )
    })


@app.route("/api/vapi/rueckfragen")
def vapi_rueckfragen():
    """Offene Rückfragen — für Vapi Tool Call."""
    if not _vapi_auth():
        return jsonify({"error": "Unauthorized"}), 401

    mandant_id = request.args.get("mandant_id", "").upper()
    all_belege = []
    if mandant_id:
        m = get_mandant(mandant_id)
        if m:
            all_belege = _load_all_belege(mandant_dirs(m)["outbox"])
    else:
        all_belege = _load_all_belege(OUTBOX_DIR)
        for m in load_mandanten():
            all_belege.extend(_load_all_belege(mandant_dirs(m)["outbox"]))

    offen = [b for b in all_belege if b.get("status") == "rueckfrage"]

    if not offen:
        return jsonify({
            "anzahl": 0,
            "nachricht": "Es gibt aktuell keine offenen Rückfragen."
        })

    beispiele = [
        f"{b.get('lieferant','?')} ({b.get('bruttobetrag','?')} EUR)"
        for b in offen[:3]
    ]
    return jsonify({
        "anzahl": len(offen),
        "beispiele": beispiele,
        "nachricht": (
            f"Es gibt {len(offen)} offene Rückfrage(n). "
            f"Zum Beispiel: {', '.join(beispiele)}. "
            f"Diese können im Dashboard unter 'Rückfragen' geprüft werden."
        )
    })


@app.route("/api/vapi/mandant-info")
def vapi_mandant_info():
    """Mandanten-Übersicht — für Vapi Tool Call."""
    if not _vapi_auth():
        return jsonify({"error": "Unauthorized"}), 401

    mandant_id = request.args.get("mandant_id", "").upper()
    if mandant_id:
        m = get_mandant(mandant_id)
        if not m:
            return jsonify({"gefunden": False, "nachricht": f"Mandant {mandant_id} nicht gefunden."})
        return jsonify({
            "gefunden":     True,
            "id":           m["id"],
            "name":         m["name"],
            "kontenrahmen": m.get("kontenrahmen", "SKR03"),
            "nachricht":    f"Mandant {m['name']} verwendet {m.get('kontenrahmen','SKR03')}."
        })

    mandanten = load_mandanten()
    namen = [m["name"] for m in mandanten]
    return jsonify({
        "anzahl":   len(mandanten),
        "mandanten": namen,
        "nachricht": f"Es sind {len(mandanten)} Mandant(en) eingerichtet: {', '.join(namen)}." if namen else "Noch keine Mandanten eingerichtet."
    })


@app.route("/api/vapi/kosten")
def vapi_kosten():
    """API-Kosten aktueller Monat — für Vapi Tool Call."""
    if not _vapi_auth():
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from tools.cost_tracker import get_costs
        daily   = get_costs("today")
        monthly = get_costs("month")
        return jsonify({
            "heute_eur":   round(daily, 4),
            "monat_eur":   round(monthly, 4),
            "nachricht":   f"Heute: {daily:.4f} EUR, diesen Monat: {monthly:.2f} EUR API-Kosten."
        })
    except Exception:
        return jsonify({"nachricht": "Kostendaten nicht verfügbar."})


# ─── Anlagenbuchhaltung ───────────────────────────────────

@app.route("/anlagen")
@login_required
def anlagen():
    from tools.anlagenbuchhaltung import get_anlagegüter, berechne_jahres_afa
    from datetime import date
    mandant_id = request.args.get("mandant_id") or (
        g.user["mandant_ids"][0] if g.user.get("mandant_ids") else None
    )
    anlagen_liste = get_anlagegüter(mandant_id)
    jahr = int(request.args.get("jahr", date.today().year))
    afa_bericht = berechne_jahres_afa(mandant_id, jahr)
    mandanten = load_mandanten()
    return render_template("anlagen.html",
                           anlagen=anlagen_liste,
                           afa_bericht=afa_bericht,
                           mandanten=mandanten,
                           aktueller_mandant=mandant_id,
                           aktuelles_jahr=jahr)


@app.route("/anlagen/erfassen", methods=["POST"])
@login_required
def anlage_erfassen():
    from tools.anlagenbuchhaltung import erfasse_anlage
    mandant_id = request.form.get("mandant_id") or None
    try:
        anlage_id = erfasse_anlage(
            bezeichnung=request.form["bezeichnung"],
            anschaffungsdatum=request.form["anschaffungsdatum"],
            anschaffungskosten=float(request.form["anschaffungskosten"]),
            nutzungsdauer_jahre=int(request.form["nutzungsdauer_jahre"]),
            lieferant=request.form.get("lieferant") or None,
            kategorie=request.form.get("kategorie", "default"),
            mandant_id=mandant_id,
            kontenrahmen=request.form.get("kontenrahmen", "SKR03"),
            notizen=request.form.get("notizen") or None,
        )
        flash(f"Anlage erfasst (ID: {anlage_id[:8]}…)", "success")
    except Exception as exc:
        flash(f"Fehler beim Erfassen: {exc}", "error")
    return redirect(url_for("anlagen", mandant_id=mandant_id))


@app.route("/anlagen/<anlage_id>/deactivate", methods=["POST"])
@login_required
def anlage_deactivate(anlage_id):
    from tools.anlagenbuchhaltung import deactivate_anlage, get_anlage
    anlage = get_anlage(anlage_id)
    if not anlage:
        flash("Anlage nicht gefunden.", "error")
        return redirect(url_for("anlagen"))
    if g.user["role"] != "admin" and g.user.get("mandant_ids"):
        if anlage.get("mandant_id") and anlage["mandant_id"] not in g.user["mandant_ids"]:
            flash("Kein Zugriff auf diese Anlage.", "error")
            return redirect(url_for("anlagen"))
    deactivate_anlage(anlage_id, request.form.get("abgangsdatum"))
    flash("Anlage als abgegangen markiert.", "success")
    return redirect(url_for("anlagen"))


# ─── Bankabgleich ─────────────────────────────────────────

@app.route("/bankabgleich")
@login_required
def bankabgleich():
    from tools.bankabgleich import get_offene_transaktionen, get_transaktionen
    mandant_id = request.args.get("mandant_id") or None
    offene = get_offene_transaktionen(mandant_id)
    alle = get_transaktionen(mandant_id, limit=50)
    mandanten = load_mandanten()
    return render_template("bankabgleich.html",
                           offene=offene,
                           transaktionen=alle,
                           mandanten=mandanten,
                           aktueller_mandant=mandant_id)


@app.route("/bankabgleich/upload", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def bankabgleich_upload():
    from tools.bankabgleich import import_datei
    mandant_id = request.form.get("mandant_id") or None
    f = request.files.get("kontoauszug")
    if not f or not f.filename:
        flash("Keine Datei ausgewählt.", "error")
        return redirect(url_for("bankabgleich"))

    import tempfile, os
    suffix = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        f.save(tmp.name)
        try:
            result = import_datei(tmp.name, mandant_id)
            flash(f"{result['typ']}: {result['neu_importiert']} neue Transaktionen importiert.", "success")
        except Exception as exc:
            flash(f"Fehler beim Import: {exc}", "error")
        finally:
            os.unlink(tmp.name)

    return redirect(url_for("bankabgleich", mandant_id=mandant_id))


@app.route("/bankabgleich/abgleich", methods=["POST"])
@login_required
def bankabgleich_run():
    from tools.bankabgleich import abgleich_durchfuehren
    mandant_id = request.form.get("mandant_id") or None
    result = abgleich_durchfuehren(mandant_id)
    flash(f"Abgleich: {result['abgeglichen']} zugeordnet, {result['offen']} offen.", "success")
    return redirect(url_for("bankabgleich", mandant_id=mandant_id))


# ─── EÜR ─────────────────────────────────────────────────

@app.route("/euer")
@login_required
def euer():
    from tools.euer import erstelle_euer_aus_db, format_euer_text
    from datetime import date
    mandant_id = request.args.get("mandant_id") or None
    jahr = int(request.args.get("jahr", date.today().year))
    kontenrahmen = request.args.get("kontenrahmen", "SKR03")

    euer_data = erstelle_euer_aus_db(mandant_id, jahr, kontenrahmen)
    euer_text = format_euer_text(euer_data)
    mandanten = load_mandanten()
    return render_template("euer.html",
                           euer=euer_data,
                           euer_text=euer_text,
                           mandanten=mandanten,
                           aktueller_mandant=mandant_id,
                           aktuelles_jahr=jahr)


# ─── Debitorenbuchhaltung ─────────────────────────────────

@app.route("/debitoren")
@login_required
def debitoren():
    from tools.debitoren import get_offene_forderungen, get_ausgangsrechnungen, get_forderungs_summary
    mandant_id = request.args.get("mandant_id") or None
    offene = get_offene_forderungen(mandant_id)
    alle = get_ausgangsrechnungen(mandant_id, limit=100)
    summary = get_forderungs_summary(mandant_id)
    mandanten = load_mandanten()
    return render_template("debitoren.html",
                           offene_forderungen=offene,
                           rechnungen=alle,
                           summary=summary,
                           mandanten=mandanten,
                           aktueller_mandant=mandant_id)


@app.route("/debitoren/erfassen", methods=["POST"])
@login_required
def debitor_erfassen():
    from tools.debitoren import erfasse_ausgangsrechnung
    mandant_id = request.form.get("mandant_id") or None
    try:
        rechnung_id = erfasse_ausgangsrechnung(
            debitor_name=request.form["debitor_name"],
            betrag_netto=float(request.form["betrag_netto"]),
            rechnungsdatum=request.form["rechnungsdatum"],
            mwst_satz=float(request.form.get("mwst_satz", 19.0)),
            rechnungsnummer=request.form.get("rechnungsnummer") or None,
            debitor_email=request.form.get("debitor_email") or None,
            zahlungsziel_tage=int(request.form.get("zahlungsziel_tage", 30)),
            buchungstext=request.form.get("buchungstext") or None,
            mandant_id=mandant_id,
            kontenrahmen=request.form.get("kontenrahmen", "SKR03"),
        )
        flash(f"Rechnung erfasst (ID: {rechnung_id[:8]}…)", "success")
    except Exception as exc:
        flash(f"Fehler: {exc}", "error")
    return redirect(url_for("debitoren", mandant_id=mandant_id))


@app.route("/debitoren/<rechnung_id>/bezahlt", methods=["POST"])
@login_required
def debitor_bezahlt(rechnung_id):
    from tools.debitoren import mark_bezahlt
    from tools.db import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ausgangsrechnungen WHERE rechnung_id = ?", (rechnung_id,)
        ).fetchone()
    if not row:
        flash("Rechnung nicht gefunden.", "error")
        return redirect(url_for("debitoren"))
    rechnung = dict(row)
    if g.user["role"] != "admin" and g.user.get("mandant_ids"):
        if rechnung.get("mandant_id") and rechnung["mandant_id"] not in g.user["mandant_ids"]:
            flash("Kein Zugriff auf diese Rechnung.", "error")
            return redirect(url_for("debitoren"))
    mark_bezahlt(rechnung_id, request.form.get("zahlungsdatum"))
    flash("Rechnung als bezahlt markiert.", "success")
    return redirect(url_for("debitoren"))


@app.route("/debitoren/<rechnung_id>/storno", methods=["POST"])
@login_required
def debitor_storno(rechnung_id):
    from tools.debitoren import storniere_rechnung
    from tools.db import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ausgangsrechnungen WHERE rechnung_id = ?", (rechnung_id,)
        ).fetchone()
    if not row:
        flash("Rechnung nicht gefunden.", "error")
        return redirect(url_for("debitoren"))
    rechnung = dict(row)
    if g.user["role"] != "admin" and g.user.get("mandant_ids"):
        if rechnung.get("mandant_id") and rechnung["mandant_id"] not in g.user["mandant_ids"]:
            flash("Kein Zugriff auf diese Rechnung.", "error")
            return redirect(url_for("debitoren"))
    storniere_rechnung(rechnung_id)
    flash("Rechnung storniert.", "success")
    return redirect(url_for("debitoren"))


@app.route("/debitoren/mahnlauf", methods=["POST"])
@login_required
def debitor_mahnlauf():
    from tools.debitoren import mahnlauf
    mandant_id = request.form.get("mandant_id") or None
    ergebnis = mahnlauf(mandant_id)
    flash(f"Mahnlauf: {len(ergebnis)} Mahnung(en) erstellt.", "success")
    return redirect(url_for("debitoren", mandant_id=mandant_id))


@app.route("/debitoren/export")
@login_required
def debitor_export():
    from tools.debitoren import erstelle_datev_export_debitoren
    mandant_id = request.args.get("mandant_id") or None
    csv_data = erstelle_datev_export_debitoren(
        mandant_id=mandant_id,
        datum_von=request.args.get("von"),
        datum_bis=request.args.get("bis"),
    )
    if not csv_data:
        flash("Keine Daten für den Export.", "error")
        return redirect(url_for("debitoren"))
    from flask import Response
    return Response(
        csv_data.encode("cp1252", errors="replace"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=DATEV_Debitoren.csv"}
    )


# ─── Legal Pages ─────────────────────────────────────────

@app.route("/impressum")
def impressum():
    return render_template("impressum.html")


@app.route("/datenschutz")
def datenschutz():
    return render_template("datenschutz.html")


# ─── IMAP-Poll (manuell oder per Scheduler) ──────────────

@app.route("/api/poll-mail", methods=["POST"])
@login_required
@csrf.exempt
def poll_mail():
    """Liest ungesehene E-Mails aus der IMAP-Inbox und speichert Anhänge mandantenspezifisch."""
    from tools.config import IMAP_HOST, IMAP_USER, IMAP_PASSWORD, INBOX_DIR
    from tools.imap_poller import poll as imap_poll
    if not IMAP_USER or not IMAP_PASSWORD:
        return jsonify({"error": "IMAP nicht konfiguriert — IMAP_USER und IMAP_PASSWORD in .env setzen"}), 400
    result = imap_poll(
        imap_host=IMAP_HOST,
        imap_user=IMAP_USER,
        imap_password=IMAP_PASSWORD,
        inbox_dir=INBOX_DIR,
        get_mandant_fn=get_mandant,
        mandant_dirs_fn=mandant_dirs,
    )
    return jsonify(result), 200


# ─── Mailgun Inbound-Webhook ──────────────────────────────

@app.route("/api/inbound-mail", methods=["POST"])
def inbound_mail():
    """Mailgun Inbound-Webhook: E-Mails an MANDANT_ID@inbox.fynaxa.de als Belege speichern."""
    import hashlib
    import hmac
    import time
    from tools.config import MAILGUN_SIGNING_KEY, INBOX_DIR, get_mandant, mandant_dirs

    # Fail-closed: ohne Signing Key wird der Webhook nicht angenommen. Sonst könnte
    # jeder, der die Adresse kennt, Belege in einen Mandanten einschleusen.
    if not MAILGUN_SIGNING_KEY:
        logger.warning("Mailgun Webhook: MAILGUN_SIGNING_KEY fehlt, Anfrage von %s abgelehnt", request.remote_addr)
        return jsonify({"error": "webhook not configured"}), 503
    token     = request.form.get("token", "")
    timestamp = request.form.get("timestamp", "")
    signature = request.form.get("signature", "")
    expected  = hmac.new(
        key=MAILGUN_SIGNING_KEY.encode(),
        msg=(timestamp + token).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        logger.warning("Mailgun Webhook: ungültige Signatur von %s", request.remote_addr)
        return jsonify({"error": "invalid signature"}), 403
    # Replay-Schutz: Timestamp darf nicht älter als 5 Minuten sein
    try:
        if abs(int(time.time()) - int(timestamp)) > 300:
            return jsonify({"error": "timestamp expired"}), 403
    except ValueError:
        return jsonify({"error": "invalid timestamp"}), 400

    # Empfänger-Adresse → Mandant-ID (muster@inbox.fynaxa.de → MUSTER)
    recipient  = request.form.get("recipient", "")
    local_part = recipient.split("@")[0].upper() if "@" in recipient else ""

    m = get_mandant(local_part) if local_part else None
    target_dir = mandant_dirs(m)["inbox"] if m else INBOX_DIR

    date_suffix   = datetime.now().strftime("%Y-%m-%d")
    target_day    = target_dir / date_suffix
    target_day.mkdir(parents=True, exist_ok=True)

    supported = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
    saved: list[str] = []

    attachment_count = int(request.form.get("attachment-count", "0"))
    for i in range(1, attachment_count + 1):
        f = request.files.get(f"attachment-{i}")
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in supported:
            logger.debug("Mailgun: Anhang '%s' übersprungen (Typ nicht unterstützt)", f.filename)
            continue
        target = target_day / f.filename
        counter = 1
        while target.exists():
            target = target_day / f"{Path(f.filename).stem}_{counter}{ext}"
            counter += 1
        f.save(str(target))
        saved.append(target.name)
        logger.info("Mailgun: %s → %s/%s", f.filename, local_part or "global", target.name)

    logger.info("Mailgun Webhook: %d Anhang/Anhänge von <%s> gespeichert", len(saved), recipient)
    return jsonify({"saved": saved, "mandant": local_part or "global"}), 200


# ─── Error Handler ────────────────────────────────────────

@app.route("/health")
def health():
    """Health-Check-Endpoint (kein Login erforderlich — für Docker/LB)."""
    from tools.monitoring import health_check
    result = health_check()
    status_code = 200 if result["healthy"] else 503
    return jsonify(result), status_code


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    from tools.settings_store import get_all, set as settings_set
    from tools.scheduler import start as sched_start, stop as sched_stop, status as sched_status

    if request.method == "POST":
        section = request.form.get("section")

        if section == "scheduler":
            active = "true" if request.form.get("scheduler_active") else "false"
            time_  = request.form.get("scheduler_time", "18:00").strip()
            settings_set("scheduler_active", active)
            settings_set("scheduler_time", time_)
            # Scheduler live neu starten oder stoppen
            if active == "true":
                sched_stop()
                sched_start()
                flash(f"Scheduler aktiviert — läuft täglich um {time_} Uhr.", "success")
            else:
                sched_stop()
                flash("Scheduler deaktiviert.", "success")

        elif section == "report_email":
            settings_set("report_email_to", request.form.get("report_email_to", "").strip())
            settings_set("public_url", request.form.get("public_url", "").strip())
            flash("Report-E-Mail-Einstellungen gespeichert.", "success")

        elif section == "imap":
            settings_set("imap_host",     request.form.get("imap_host", "").strip())
            settings_set("smtp_host",     request.form.get("smtp_host", "").strip())
            settings_set("imap_user",     request.form.get("imap_user", "").strip())
            pw = request.form.get("imap_password", "").strip()
            if pw and pw != "••••••••••••••••":
                settings_set("imap_password", pw)
            flash("E-Mail-Einstellungen gespeichert.", "success")

        elif section == "pipeline":
            settings_set("konfidenz_schwelle", request.form.get("konfidenz_schwelle", "0.7").strip())
            settings_set("daily_budget_eur",   request.form.get("daily_budget_eur", "10.00").strip())
            settings_set("monthly_budget_eur", request.form.get("monthly_budget_eur", "100.00").strip())
            flash("Pipeline-Einstellungen gespeichert.", "success")

        elif section == "vapi":
            settings_set("vapi_secret",       request.form.get("vapi_secret", "").strip())
            settings_set("vapi_phone_number", request.form.get("vapi_phone_number", "").strip())
            flash("Vapi-Einstellungen gespeichert.", "success")

        return redirect(url_for("admin_settings"))

    return render_template("admin_settings.html",
                           s=get_all(),
                           scheduler_status=sched_status())


@app.route("/admin/onboarding", methods=["GET", "POST"])
@admin_required
def admin_onboarding():
    """Neuen Mandanten in einem Schritt onboarden."""
    from tools.settings_store import get as cfg_get
    from tools.auth import create_user
    from tools.report_email import send_welcome
    import re, string, random

    def _gen_password(length: int = 12) -> str:
        chars = string.ascii_letters + string.digits + "!@#$%"
        return "".join(random.SystemRandom().choice(chars) for _ in range(length))

    def _slug(name: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", name.upper())[:10]

    result = None

    if request.method == "POST":
        kanzlei_name  = request.form.get("kanzlei_name", "").strip()
        email         = request.form.get("email", "").strip()
        mandant_id    = request.form.get("mandant_id", "").strip().upper() or _slug(kanzlei_name)
        berater_nr    = request.form.get("berater_nr", "").strip()
        mandant_nr    = request.form.get("mandant_nr", "").strip()
        kontenrahmen  = request.form.get("kontenrahmen", "SKR03")
        send_email    = request.form.get("send_welcome_email") == "1"

        if not kanzlei_name or not email:
            flash("Kanzleiname und E-Mail sind Pflichtfelder.", "error")
        elif not mandant_id.replace("-", "").replace("_", "").isalnum():
            flash("Mandanten-ID darf nur Buchstaben, Zahlen, - und _ enthalten.", "error")
        else:
            password = _gen_password()
            username = mandant_id.lower()

            # Mandant anlegen
            mandant = {
                "id": mandant_id,
                "name": kanzlei_name,
                "kontenrahmen": kontenrahmen,
                "berater_nr": berater_nr,
                "mandant_nr": mandant_nr,
                "inbox":  f"inbox/{mandant_id}",
                "outbox": f"outbox/{mandant_id}",
                "archiv": f"archiv/{mandant_id}",
                "eigene_regeln": [],
                "notizen": "",
                "report_email": email,
            }
            mandant_ok = add_mandant(mandant)
            if mandant_ok:
                mandant_dirs(mandant)

            # Benutzer anlegen
            user_ok = create_user(username, password,
                                  display_name=kanzlei_name,
                                  role="user",
                                  mandant_ids=[mandant_id])

            # Plus-Adresse berechnen
            imap_user   = cfg_get("imap_user") or ""
            plus_local  = imap_user.split("@")[0] if "@" in imap_user else imap_user
            imap_domain = imap_user.split("@")[1] if "@" in imap_user else "gmail.com"
            plus_address = f"{plus_local}+{mandant_id.lower()}@{imap_domain}"

            # Login-URL
            public_url = cfg_get("public_url") or ""
            login_url  = public_url.rstrip("/") or "http://localhost:5001"

            # Welcome-E-Mail
            email_sent = False
            if send_email and imap_user:
                email_sent = send_welcome(
                    to_email     = email,
                    display_name = kanzlei_name,
                    username     = username,
                    password     = password,
                    login_url    = login_url,
                    plus_address = plus_address,
                )

            if not mandant_ok:
                flash(f"Mandant '{mandant_id}' existiert bereits — Benutzer trotzdem angelegt.", "error" if not user_ok else "success")
            elif not user_ok:
                flash(f"Benutzer '{username}' konnte nicht angelegt werden (existiert bereits?).", "error")
            else:
                result = {
                    "kanzlei_name": kanzlei_name,
                    "mandant_id":   mandant_id,
                    "username":     username,
                    "password":     password,
                    "plus_address": plus_address,
                    "login_url":    login_url,
                    "email_sent":   email_sent,
                    "to_email":     email,
                }

    return render_template("admin_onboarding.html", result=result,
                           imap_configured=bool(cfg_get("imap_user")))


@app.route("/admin/vapi-config")
@admin_required
def vapi_config_download():
    """Gibt die Vapi Tool-Konfiguration als JSON zurück — direkt in Vapi einfügen."""
    from tools.settings_store import get
    base = (get("public_url") or "https://app.fibo-agent.com").rstrip("/")
    secret = get("vapi_secret") or "DEIN_SECRET_HIER"

    config = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "pipeline_status",
                    "description": "Gibt den Status des letzten Pipeline-Runs zurück: wann lief er, wie viele Belege wurden verarbeitet und exportiert.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mandant_id": {
                                "type": "string",
                                "description": "Optionale Mandanten-ID (z.B. MUSTER). Leer lassen für globalen Status."
                            }
                        },
                        "required": []
                    }
                },
                "server": {
                    "url": f"{base}/api/vapi/pipeline-status",
                    "secret": secret
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "rueckfragen_status",
                    "description": "Gibt die Anzahl offener Rückfragen zurück — Belege die manuell geprüft werden müssen.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mandant_id": {
                                "type": "string",
                                "description": "Optionale Mandanten-ID. Leer lassen für alle Mandanten."
                            }
                        },
                        "required": []
                    }
                },
                "server": {
                    "url": f"{base}/api/vapi/rueckfragen",
                    "secret": secret
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "mandant_info",
                    "description": "Gibt Informationen zu einem Mandanten oder die Liste aller Mandanten zurück.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mandant_id": {
                                "type": "string",
                                "description": "Mandanten-ID für Details. Leer lassen für alle."
                            }
                        },
                        "required": []
                    }
                },
                "server": {
                    "url": f"{base}/api/vapi/mandant-info",
                    "secret": secret
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "api_kosten",
                    "description": "Gibt die aktuellen API-Kosten für heute und den laufenden Monat zurück.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                "server": {
                    "url": f"{base}/api/vapi/kosten",
                    "secret": secret
                }
            }
        ]
    }

    from flask import Response
    import json
    return Response(
        json.dumps(config, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=vapi_tools.json"}
    )


@app.route("/admin/test-imap")
@admin_required
def test_imap_connection():
    """Testet die IMAP-Verbindung und gibt das Ergebnis als Flash-Nachricht aus."""
    from tools.settings_store import get
    import imaplib
    host = get("imap_host")
    user = get("imap_user")
    pw   = get("imap_password")
    if not user or not pw:
        flash("IMAP nicht konfiguriert — bitte zuerst Zugangsdaten speichern.", "error")
        return redirect(url_for("admin_settings"))
    try:
        conn = imaplib.IMAP4_SSL(host)
        conn.login(user, pw)
        _, data = conn.search(None, "UNSEEN")
        unread = len(data[0].split()) if data[0] else 0
        conn.logout()
        flash(f"IMAP-Verbindung erfolgreich ({user}) · {unread} ungelesene Mail(s).", "success")
    except Exception as exc:
        flash(f"IMAP-Verbindung fehlgeschlagen: {exc}", "error")
    return redirect(url_for("admin_settings"))


@app.route("/admin/monitoring")
@admin_required
def admin_monitoring():
    """Detailliertes System-Monitoring (Admin only)."""
    from tools.monitoring import health_check
    from tools.cost_tracker import get_costs, get_summary
    from tools.scheduler import status as scheduler_status
    health = health_check()
    daily = get_costs("today")
    monthly = get_costs("month")
    return render_template("admin_monitoring.html",
                           health=health, daily=daily, monthly=monthly,
                           scheduler=scheduler_status())


@app.errorhandler(429)
def rate_limit_exceeded(e):
    flash("Zu viele Anfragen. Bitte warte einen Moment.", "error")
    return redirect(url_for("dashboard")), 429


@app.errorhandler(404)
def not_found(e):
    flash("Seite nicht gefunden.", "error")
    return redirect(url_for("dashboard"))


@app.errorhandler(500)
def server_error(e):
    logger.exception("Interner Serverfehler: %s", e)
    flash("Ein interner Fehler ist aufgetreten. Bitte versuche es erneut.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/demo-reset", methods=["POST"])
@admin_required
def admin_demo_reset():
    """Setzt den DEMO-Mandanten zurück: DB-Einträge löschen + Inbox leeren."""
    try:
        from tools.config import ROOT
        import sqlite3
        db_path = ROOT / "data" / "fibu_agent.db"
        con = sqlite3.connect(str(db_path))
        deleted_belege = con.execute("DELETE FROM belege WHERE mandant_id IN ('DEMO','DEMO2')").rowcount
        deleted_runs = con.execute("DELETE FROM runs WHERE mandant_id IN ('DEMO','DEMO2')").rowcount
        con.commit()
        con.close()

        demo_inbox = ROOT / "inbox" / "DEMO"
        removed = 0
        if demo_inbox.exists():
            for f in demo_inbox.glob("*"):
                f.unlink()
                removed += 1

        flash(f"DEMO zurückgesetzt: {deleted_belege} Belege, {removed} Dateien gelöscht.", "success")
    except Exception as exc:
        logger.exception("Demo-Reset fehlgeschlagen: %s", exc)
        flash(f"Reset fehlgeschlagen: {exc}", "error")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=5001)
