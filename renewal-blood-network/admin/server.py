"""
==============================================================================
RENEWAL BLOOD NETWORK — Admin Dashboard Python MySQL/MariaDB REST Server
==============================================================================

Port: 8081 (Default, override with --port <num> or ADMIN_PORT=<num>)
Framework: Flask (Native Python)
Database: Shared MySQL / MariaDB via ../db.py

Features:
 - Full MIME type and static asset serving for admin dashboard
 - Smart SPA fallback to admin/index.html
 - Built-in SVG Favicon server (zero 404s for favicon.ico)
 - Secured Admin REST API for Donors, Verification, Emergency Queue & Contacts
 - Colored terminal logging with request timing
 - Health check endpoint: /api/health
==============================================================================
"""

import os
import sys
import time
import base64
import re
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response, send_from_directory
import json
import threading
import urllib.request
import urllib.parse
from flask_sock import Sock

# Add parent directory to module search path to import db.py
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)
import db

ADMIN_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Load .env helper from parent folder ───────────────────────
env_file = os.path.join(PARENT_DIR, '.env')
if os.path.isfile(env_file):
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ── Cloudflare Turnstile Configuration ────────────────────────
def get_turnstile_config():
    """Dynamically reads Turnstile config and reloads .env if updated."""
    if os.path.isfile(env_file):
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    site_key = os.environ.get('CLOUDFLARE_TURNSTILE_SITE_KEY') or os.environ.get('TURNSTILE_SITE_KEY') or '1x00000000000000000000AA'
    secret_key = os.environ.get('CLOUDFLARE_TURNSTILE_SECRET_KEY') or os.environ.get('TURNSTILE_SECRET_KEY') or '1x0000000000000000000000000000000AA'
    enabled = os.environ.get('TURNSTILE_ENABLED', 'true').lower() in ('1', 'true', 'yes')
    return site_key, secret_key, enabled

def verify_turnstile(token, remote_ip=None):
    """Verifies Cloudflare Turnstile token."""
    site_key, secret_key, enabled = get_turnstile_config()
    if not enabled:
        return True, ""
    token_str = str(token or '').strip()
    if not token_str:
        return False, "অনুগ্রহ করে ক্যাপচা (Turnstile) যাচাই সম্পন্ন করুন।"
    try:
        url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
        post_data = {'secret': secret_key, 'response': token_str}
        if remote_ip:
            post_data['remoteip'] = remote_ip
        data = urllib.parse.urlencode(post_data).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            if res.get('success'):
                return True, ""
            return False, "ক্যাপচা (Turnstile) যাচাই ব্যর্থ হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।"
    except Exception as e:
        if secret_key.startswith('1x00000000'):
            return True, ""
        return False, "ক্যাপচা সার্ভারের সাথে সংযোগ করা সম্ভব হয়নি।"

# Parse CLI arguments
port = int(os.environ.get('ADMIN_PORT', 8081))
if '--port' in sys.argv:
    try:
        idx = sys.argv.index('--port')
        port = int(sys.argv[idx + 1])
    except (IndexError, ValueError):
        pass

HOST = os.environ.get('HOST', '0.0.0.0')

app = Flask(__name__, static_folder=None)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True
sock = Sock(app)

# ── WebSocket Admin Real-Time Manager ─────────────────────────
_admin_ws_clients = set()
_admin_ws_lock = threading.Lock()

def get_admin_realtime_payload():
    try:
        return {"type": "sync", "version": db.get_data_version()}
    except Exception as e:
        return {"type": "sync", "version": str(time.time()), "error": str(e)}

def broadcast_admin_realtime(payload=None):
    if payload is None:
        payload = get_admin_realtime_payload()
    raw = json.dumps(payload)
    with _admin_ws_lock:
        clients = list(_admin_ws_clients)
    for ws in clients:
        try:
            ws.send(raw)
        except Exception:
            with _admin_ws_lock:
                _admin_ws_clients.discard(ws)

@sock.route('/ws/realtime')
def admin_realtime_ws(ws):
    with _admin_ws_lock:
        _admin_ws_clients.add(ws)
    try:
        ws.send(json.dumps(get_admin_realtime_payload()))
        while True:
            msg = ws.receive(timeout=25)
            if msg == 'ping':
                ws.send(json.dumps({'type': 'pong'}))
    except Exception:
        pass
    finally:
        with _admin_ws_lock:
            _admin_ws_clients.discard(ws)

def _start_admin_realtime_watcher():
    def watcher():
        last_ver = db.get_data_version()
        while True:
            try:
                time.sleep(0.5)
                cur_ver = db.get_data_version()
                if cur_ver != last_ver:
                    last_ver = cur_ver
                    broadcast_admin_realtime()
            except Exception:
                pass
    t = threading.Thread(target=watcher, daemon=True)
    t.start()

_start_admin_realtime_watcher()

server_start_time = time.time()

# ── Built-in Favicon SVG Data ─────────────────────────────────
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <path fill="#E11D48" d="M50 8 C50 8 18 46 18 68 C18 86 32 94 50 94 C68 94 82 86 82 68 C82 46 50 8 50 8 Z"/>
  <path fill="#FFFFFF" opacity="0.3" d="M42 35 C38 48 30 65 30 72 C30 76 34 80 40 82 C34 76 35 58 45 42 C48 38 46 32 42 35 Z"/>
</svg>"""

# ANSI Color Helpers
C_RESET   = "\033[0m"
C_BRIGHT  = "\033[1m"
C_DIM     = "\033[2m"
C_RED     = "\033[31m"
C_GREEN   = "\033[32m"
C_YELLOW  = "\033[33m"
C_CYAN    = "\033[36m"

@app.before_request
def start_timer():
    request._start_time = time.time()

@app.after_request
def apply_headers_and_log(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Range'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'

    # Strict Anti-Caching
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, post-check=0, pre-check=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    response.headers['Surrogate-Control'] = 'no-store'

    try:
        dur_ms = (time.time() - getattr(request, '_start_time', time.time())) * 1000
        now_str = datetime.now().strftime("%H:%M:%S")
        status = response.status_code

        color = C_GREEN
        if status >= 500:
            color = C_RED
        elif status >= 400:
            color = C_YELLOW
        elif status >= 300:
            color = C_CYAN

        print(f"[{now_str}] {C_BRIGHT}{request.method}{C_RESET} {request.path} {color}{status}{C_RESET} {C_DIM}{dur_ms:.1f}ms{C_RESET}")
    except Exception:
        pass

    return response

# ── Admin Auth Helper ─────────────────────────────────────────
import secrets
import hashlib

active_admin_tokens = set()

def get_fallback_token():
    admin_password = os.environ.get('ADMIN_PASSWORD', '').strip()
    if not admin_password:
        return None
    return hashlib.sha256(('RBN_SALT_' + admin_password).encode('utf-8')).hexdigest()

def require_admin_auth():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False
    token = auth_header[7:].strip()
    fallback = get_fallback_token()
    return (token in active_admin_tokens) or (fallback is not None and token == fallback)

# ── Favicon Handlers ──────────────────────────────────────────
@app.route('/favicon.ico')
@app.route('/favicon.svg')
def favicon():
    return Response(FAVICON_SVG, mimetype='image/svg+xml')

# ═════════════════════════════════════════════════════════════
# ADMIN REST API ROUTES
# ═════════════════════════════════════════════════════════════

@app.route('/api/realtime/version', methods=['GET'])
def admin_realtime_version():
    return jsonify({"version": db.get_data_version()}), 200

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "Renewal Blood Network Admin Server (Python)",
        "uptime": round(time.time() - server_start_time, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    pwd = data.get('password')
    turnstile_token = data.get('turnstile_token') or data.get('cf-turnstile-response')
    admin_password = os.environ.get('ADMIN_PASSWORD', '').strip()
    if not admin_password:
        return jsonify({"success": False, "error": "ADMIN_PASSWORD সেট করা নেই (.env চেক করুন)"}), 500

    _, _, enabled = get_turnstile_config()
    if enabled:
        ok, err_msg = verify_turnstile(turnstile_token, request.remote_addr)
        if not ok:
            return jsonify({"success": False, "error": err_msg, "turnstileFailed": True}), 400

    if pwd == admin_password:
        # Cryptographically secure random session token
        token = secrets.token_hex(32)
        active_admin_tokens.add(token)
        return jsonify({"success": True, "token": token}), 200
    return jsonify({"success": False, "error": "ভুল পাসওয়ার্ড / Invalid password"}), 401

@app.route('/api/config', methods=['GET'])
def admin_config():
    site_key, _, enabled = get_turnstile_config()
    return jsonify({
        "database": "mysql",
        "python": True,
        "turnstileSiteKey": site_key,
        "turnstileEnabled": enabled
    })

# ── Protected Admin Endpoints ─────────────────────────────────

@app.before_request
def protect_admin_api():
    # Only protect /api/ routes, excluding health, login, version, and config
    if request.path.startswith('/api/'):
        if request.path in ('/api/health', '/api/admin/login', '/api/realtime/version', '/api/config'):
            return None
        if not require_admin_auth():
            return jsonify({"error": "Unauthorized"}), 401
    return None

@app.route('/api/donors', methods=['GET'])
def admin_donors_list():
    donors = db.get_donors()
    return jsonify(donors), 200

@app.route('/api/donors/<donor_id>', methods=['GET'])
def admin_donors_detail(donor_id):
    donor = db.get_donor_by_id(donor_id)
    if not donor:
        return jsonify({"error": "Donor not found"}), 404
    return jsonify(donor), 200

@app.route('/api/donors/<donor_id>', methods=['PUT'])
def admin_donors_update(donor_id):
    body = request.get_json(silent=True) or {}
    db.update_donor(donor_id, body)
    updated = db.get_donor_by_id(donor_id)
    return jsonify(updated or {"success": True}), 200

@app.route('/api/requests', methods=['GET'])
def admin_requests_list():
    reqs = db.get_requests()
    return jsonify(reqs), 200

@app.route('/api/requests/<req_id>', methods=['PUT'])
def admin_requests_update(req_id):
    body = request.get_json(silent=True) or {}
    db.update_request(req_id, body)
    updated = db.get_request_by_id(req_id)
    return jsonify(updated or {"success": True}), 200

@app.route('/api/contacts', methods=['GET'])
def admin_contacts_list():
    contacts = db.get_contact_requests()
    return jsonify(contacts), 200

@app.route('/api/contacts/<contact_id>', methods=['PUT'])
def admin_contacts_update(contact_id):
    body = request.get_json(silent=True) or {}
    db.update_contact_request(contact_id, body)
    updated = db.get_contact_request_by_id(contact_id)
    return jsonify(updated or {"success": True}), 200

# ═════════════════════════════════════════════════════════════
# STATIC ASSETS & SPA ROUTING (ADMIN)
# ═════════════════════════════════════════════════════════════

def get_file_hash(rel_path: str) -> str:
    clean_rel = re.sub(r'^\.?/+', '', rel_path.split('?')[0])
    full_path = os.path.normpath(os.path.join(ADMIN_DIR, clean_rel))
    if not os.path.isfile(full_path):
        full_path = os.path.normpath(os.path.join(ROOT_DIR, clean_rel))
    try:
        if os.path.isfile(full_path):
            return hex(int(os.path.getmtime(full_path)))[2:]
    except Exception:
        pass
    return hex(int(time.time()))[2:]

def process_html(content: str) -> str:
    def replace_asset(match):
        attr = match.group(1)
        raw_path = match.group(2)
        clean_path = re.sub(r'^\.?/+', '', raw_path.split('?')[0])
        h = get_file_hash(clean_path)
        prefix = '/' if raw_path.startswith('/') else ''
        return f'{attr}="{prefix}{clean_path}?v={h}"'

    transformed = re.sub(
        r'(href|src)=["\'](\.?/?(?:css|js)/[^"\']+)["\']',
        replace_asset,
        content,
        flags=re.IGNORECASE
    )

    if '<head>' in transformed and 'http-equiv="Cache-Control"' not in transformed:
        meta_tags = (
            '\n  <!-- Automated Anti-Cache Headers (Injected by Server) -->\n'
            '  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />\n'
            '  <meta http-equiv="Pragma" content="no-cache" />\n'
            '  <meta http-equiv="Expires" content="0" />\n'
        )
        transformed = transformed.replace('<head>', '<head>' + meta_tags, 1)

    return transformed

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_admin_static(path):
    if path.startswith('api/'):
        return jsonify({"error": "API route not found"}), 404

    full_path = os.path.join(ADMIN_DIR, path)

    if path and os.path.isfile(full_path):
        if path.endswith('.html'):
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return Response(process_html(content), mimetype='text/html; charset=utf-8')
            except Exception:
                pass
        return send_from_directory(ADMIN_DIR, path)

    # SPA Fallback to admin/index.html
    index_path = os.path.join(ADMIN_DIR, 'index.html')
    if os.path.isfile(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return Response(process_html(content), mimetype='text/html; charset=utf-8')
        except Exception:
            return send_from_directory(ADMIN_DIR, 'index.html')

    return "<h1>404 — Admin File Not Found</h1>", 404

if __name__ == '__main__':
    local_url = f"http://localhost:{port}"
    net_url = f"http://127.0.0.1:{port}"

    print("\n" + "=" * 64)
    print(f"{C_BRIGHT}{C_RED}  🩸 RENEWAL BLOOD NETWORK — ADMIN PYTHON SERVER RUNNING{C_RESET}")
    print("=" * 64)
    print(f"  {C_GREEN}● Local Access:{C_RESET}    {C_CYAN}{local_url}{C_RESET}")
    print(f"  {C_GREEN}● Network Access:{C_RESET}  {C_CYAN}{net_url}{C_RESET}")
    print(f"  {C_GREEN}● Port:{C_RESET}            {C_BRIGHT}{port}{C_RESET}")
    print(f"  {C_GREEN}● Directory:{C_RESET}       {ADMIN_DIR}")
    print(f"  {C_GREEN}● Database:{C_RESET}        Shared MySQL/MariaDB ({getattr(db, 'DB_NAME', 'renewal_blood')})")
    print(f"  {C_GREEN}● Engine:{C_RESET}          Python 3 + Flask + PyMySQL")
    print("=" * 64 + "\n")

    app.run(host=HOST, port=port, threaded=True, debug=False)

