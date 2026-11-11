"""
==============================================================================
RENEWAL BLOOD NETWORK — High-Performance Python MySQL/MariaDB REST API & Server
==============================================================================

Port: 5500 (Default, override with --port <num> or PORT=<num>)
Framework: Flask (Native Python)
Database: MySQL / MariaDB via db.py

Features:
 - Full MIME type and static asset serving
 - Smart SPA (Single Page Application) routing fallback to index.html
 - Built-in SVG Favicon server (zero 404s for favicon.ico)
 - Dynamic cache-busting and strict anti-caching headers
 - Colored terminal logging with request timing
 - Full REST API for Auth, Donors, Emergency Requests, & Contact Requests
 - CORS enabled
 - Health check endpoint: /api/health
==============================================================================
"""

import os
import sys
import time
import re
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response, send_from_directory
import json
import threading
import urllib.request
import urllib.parse
from flask_sock import Sock
import db

# ── Load .env helper ──────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
env_file = os.path.join(ROOT_DIR, '.env')
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
    """
    Verifies Cloudflare Turnstile token via Cloudflare's siteverify endpoint.
    Returns (success: bool, error_msg: str)
    """
    site_key, secret_key, enabled = get_turnstile_config()
    if not enabled:
        return True, ""

    token_str = str(token or '').strip()
    if not token_str:
        return False, "অনুগ্রহ করে ক্যাপচা (Turnstile) যাচাই সম্পন্ন করুন।"

    try:
        url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
        post_data = {
            'secret': secret_key,
            'response': token_str
        }
        if remote_ip:
            post_data['remoteip'] = remote_ip

        data = urllib.parse.urlencode(post_data).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            if res.get('success'):
                return True, ""
            error_codes = res.get('error-codes', [])
            print(f"[Turnstile] Verification failed: {error_codes}")
            return False, "ক্যাপচা (Turnstile) যাচাই ব্যর্থ হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।"
    except Exception as e:
        print(f"[Turnstile] Error reaching Cloudflare: {e}")
        # In offline local development with test keys, allow pass so dev workflow is not disrupted
        if secret_key.startswith('1x00000000'):
            print("[Turnstile] Offline dev mode fallback: passing test key.")
            return True, ""
        return False, "ক্যাপচা সার্ভারের সাথে সংযোগ করা সম্ভব হয়নি।"

# ── Google OAuth Configuration ────────────────────────────────
def get_google_config():
    """Dynamically reads Google OAuth config and reloads .env if updated."""
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
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
    enabled = os.environ.get('GOOGLE_LOGIN_ENABLED', 'true').lower() in ('1', 'true', 'yes')
    return client_id, enabled

def verify_google_token(credential: str):
    """
    Verifies Google ID Token via Google's official tokeninfo endpoint.
    Returns (user_info: dict, error_msg: str)
    """
    if not credential:
        return None, "গুগল ক্রেডেনশিয়াল টোকেন পাওয়া যায়নি।"

    client_id, enabled = get_google_config()
    if not enabled:
        return None, "গুগল সাইন-ইন বর্তমানে নিষ্ক্রিয় আছে।"

    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}"
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        iss = data.get('iss', '')
        if iss not in ('accounts.google.com', 'https://accounts.google.com'):
            return None, "অবৈধ গুগল অথেনটিকেশন ইস্যুয়ার।"

        # If client_id is set in .env, verify audience
        if client_id and data.get('aud') != client_id:
            print(f"[Google Auth] Audience mismatch: expected '{client_id}', got '{data.get('aud')}'")
            return None, "গুগল ক্লায়েন্ট আইডি মিলছে না (Client ID mismatch)।"

        email = data.get('email')
        if not email:
            return None, "গুগল অ্যাকাউন্ট থেকে ইমেইল পাওয়া যায়নি।"

        return {
            "sub": data.get('sub'),
            "email": email.lower().strip(),
            "name": data.get('name') or email.split('@')[0],
            "picture": data.get('picture'),
            "email_verified": str(data.get('email_verified', '')).lower() in ('true', '1')
        }, ""
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode('utf-8'))
            err_desc = err_body.get('error_description') or err_body.get('error') or 'Invalid token'
            return None, f"গুগল টোকেন যাচাই ব্যর্থ: {err_desc}"
        except Exception:
            return None, "গুগল টোকেন অবৈধ বা মেয়াদোত্তীর্ণ।"
    except Exception as e:
        print(f"[Google Auth] Error contacting Google API: {e}")
        return None, f"গুগল সার্ভারের সাথে সংযোগ করা সম্ভব হয়নি: {str(e)}"

# Parse CLI arguments
port = int(os.environ.get('PORT', 5500))
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

# ── WebSocket Real-Time Manager ─────────────────────────────
_ws_clients = set()
_ws_lock = threading.Lock()

def get_realtime_payload():
    try:
        conn = db.get_db()
        version = db.get_data_version()
        stats = conn.execute("""
            SELECT 
                (SELECT COUNT(*) FROM donors) as total_donors,
                (SELECT COUNT(*) FROM donors WHERE availability = 'available') as available_donors,
                (SELECT COUNT(DISTINCT district) FROM donors WHERE district IS NOT NULL AND district != '') as active_districts,
                (SELECT COUNT(*) FROM blood_requests WHERE status IN ('verified', 'under_review')) as active_requests
        """).fetchone()
        conn.close()
        return {
            "type": "sync",
            "version": version,
            "totalDonors": stats["total_donors"] if stats else 0,
            "availableDonors": stats["available_donors"] if stats else 0,
            "activeDistricts": stats["active_districts"] if stats else 0,
            "activeRequests": stats["active_requests"] if stats else 0,
        }
    except Exception as e:
        return {"type": "sync", "version": str(time.time()), "error": str(e)}

def broadcast_realtime(payload=None):
    if payload is None:
        payload = get_realtime_payload()
    raw = json.dumps(payload)
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            ws.send(raw)
        except Exception:
            with _ws_lock:
                _ws_clients.discard(ws)

@sock.route('/ws/realtime')
def realtime_ws(ws):
    with _ws_lock:
        _ws_clients.add(ws)
    try:
        ws.send(json.dumps(get_realtime_payload()))
        while True:
            msg = ws.receive(timeout=25)
            if msg == 'ping':
                ws.send(json.dumps({'type': 'pong'}))
    except Exception:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)

def _start_realtime_watcher():
    def watcher():
        last_ver = db.get_data_version()
        while True:
            try:
                time.sleep(0.5)
                cur_ver = db.get_data_version()
                if cur_ver != last_ver:
                    last_ver = cur_ver
                    broadcast_realtime()
            except Exception:
                pass
    t = threading.Thread(target=watcher, daemon=True)
    t.start()

_start_realtime_watcher()

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
    # CORS Headers
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Range'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'

    # Strict Anti-Caching (Guarantees every browser refresh fetches latest file updates)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, post-check=0, pre-check=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    response.headers['Surrogate-Control'] = 'no-store'

    # Terminal Logging
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

# ── Auth Helper ───────────────────────────────────────────────
def get_auth_user():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header[7:].strip()
    return db.get_session_user(token)

# ── Privacy & Obfuscation Helpers ─────────────────────────────
def mask_phone(phone: str) -> str:
    """Masks phone number for public display (e.g. 01711002233 -> 0171***233)."""
    if not phone:
        return ""
    p = str(phone).strip()
    if p.startswith('+88'):
        if len(p) >= 11:
            return p[:7] + "***" + p[-3:]
    elif len(p) == 11:
        return p[:4] + "***" + p[-3:]
    elif len(p) > 6:
        return p[:3] + "***" + p[-2:]
    return "***"

def mask_name(name: str) -> str:
    """Masks first word / name token for public display (e.g. ডাঃ তানভীর হাসান -> ড*** তানভীর হাসান)."""
    if not name:
        return ""
    name_str = str(name).strip()
    parts = name_str.split()
    if not parts:
        return name_str
    first_char = parts[0][0]
    rest = " ".join(parts[1:])
    return f"{first_char}*** {rest}".strip() if rest else f"{first_char}***"

def obfuscate_donor(donor: dict, auth_user: dict = None) -> dict:
    """
    Obfuscates sensitive donor PII (phone, name, altPhone, userId) for public/unauthenticated requests.
    Only the profile owner receives unmasked personal information.
    """
    if not donor:
        return donor
    
    is_owner = False
    if auth_user:
        auth_uid = auth_user.get('id')
        auth_phone = auth_user.get('phone')
        donor_uid = donor.get('userId') or donor.get('user_id')
        donor_id = donor.get('id')
        donor_phone = donor.get('phone')
        if (auth_uid and auth_uid in (donor_uid, donor_id)) or (auth_phone and auth_phone == donor_phone):
            is_owner = True

    if is_owner:
        d_copy = dict(donor)
        d_copy['isOwner'] = True
        return d_copy

    d_copy = dict(donor)
    d_copy['name'] = mask_name(d_copy.get('name'))
    if d_copy.get('nameEn'):
        d_copy['nameEn'] = mask_name(d_copy.get('nameEn'))
    d_copy['phone'] = mask_phone(d_copy.get('phone'))
    if d_copy.get('altPhone'):
        d_copy['altPhone'] = mask_phone(d_copy.get('altPhone'))
    # Conceal internal auth userId from public view
    d_copy['userId'] = None
    d_copy['isObfuscated'] = True
    return d_copy

def obfuscate_request(req: dict, auth_user: dict = None) -> dict:
    """
    Obfuscates blood request contact details for unauthenticated scrapers/bots.
    """
    if not req:
        return req

    is_owner = False
    if auth_user:
        auth_uid = auth_user.get('id')
        auth_phone = auth_user.get('phone')
        req_uid = req.get('userId') or req.get('user_id')
        req_contact = req.get('contact')
        if (auth_uid and auth_uid == req_uid) or (auth_phone and auth_phone == req_contact):
            is_owner = True

    if is_owner:
        r_copy = dict(req)
        r_copy['isOwner'] = True
        return r_copy

    r_copy = dict(req)
    if not auth_user:
        r_copy['contact'] = mask_phone(r_copy.get('contact'))
        if r_copy.get('attendantName'):
            r_copy['attendantName'] = mask_name(r_copy.get('attendantName'))
        r_copy['userId'] = None
        r_copy['isObfuscated'] = True
    return r_copy

# ── Favicon Handlers ──────────────────────────────────────────
@app.route('/favicon.ico')
@app.route('/favicon.svg')
def favicon():
    return Response(FAVICON_SVG, mimetype='image/svg+xml')

# ═══════════════════════════════════════════════════════════════
# REST API ROUTES (/api/*)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "Renewal Blood Network Server (Python)",
        "uptime": round(time.time() - server_start_time, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.route('/api/config', methods=['GET'])
def config():
    site_key, _, enabled = get_turnstile_config()
    google_client_id, google_enabled = get_google_config()
    return jsonify({
        "database": "mysql",
        "python": True,
        "turnstileSiteKey": site_key,
        "turnstileEnabled": enabled,
        "googleClientId": google_client_id,
        "googleLoginEnabled": google_enabled
    })

@app.route('/api/realtime/version', methods=['GET'])
def realtime_version():
    conn = db.get_db()
    version = db.get_data_version()
    stats = conn.execute("""
        SELECT 
            (SELECT COUNT(*) FROM donors) as total_donors,
            (SELECT COUNT(*) FROM donors WHERE availability = 'available') as available_donors,
            (SELECT COUNT(DISTINCT district) FROM donors WHERE district IS NOT NULL AND district != '') as active_districts,
            (SELECT COUNT(*) FROM blood_requests WHERE status IN ('verified', 'under_review')) as active_requests
    """).fetchone()
    conn.close()
    return jsonify({
        "version": version,
        "totalDonors": stats["total_donors"],
        "availableDonors": stats["available_donors"],
        "activeDistricts": stats["active_districts"],
        "activeRequests": stats["active_requests"]
    }), 200

# ── Auth Endpoints ────────────────────────────────────────────

@app.route('/api/auth/check-phone', methods=['GET'])
def auth_check_phone():
    phone = (request.args.get('phone') or '').strip()
    if not phone:
        return jsonify({"error": "Phone number required"}), 400

    existing_user = db.get_user_by_phone(phone)
    existing_donor = db.get_donor_by_phone(phone)

    if existing_donor or existing_user:
        name = ""
        if existing_donor and existing_donor.get("name"):
            name = mask_name(existing_donor["name"])
        return jsonify({
            "exists": True,
            "registered": True,
            "name": name,
            "message": "এই মোবাইল নম্বর দিয়ে ইতিমধ্যেই একজন রক্তদাতা নিবন্ধিত আছেন।"
        }), 200

    return jsonify({"exists": False, "registered": False}), 200

@app.route('/api/auth/google', methods=['POST'])
def auth_google():
    data = request.get_json(silent=True) or {}
    credential = data.get('credential')
    phone = (data.get('phone') or '').strip()

    info, err = verify_google_token(credential)
    if not info:
        return jsonify({"error": err}), 400

    sub = info['sub']
    email = info['email']
    name = info['name']
    picture = info['picture']

    # 1. Check if user already exists via Google OAuth
    existing_user = db.get_user_by_oauth('google', sub)
    is_new = False

    if existing_user:
        user = existing_user
        db.link_oauth_account(user['id'], 'google', sub, email, name, picture)
    else:
        # 2. Check if user exists with matching email
        user_by_email = db.get_user_by_email(email)
        if user_by_email:
            user = db.link_oauth_account(user_by_email['id'], 'google', sub, email, name, picture)
        else:
            # 3. Create a brand new user
            user = db.create_oauth_user('google', sub, email, name, picture, phone=phone if phone else None)
            is_new = True

    # If phone was provided and user doesn't have phone, update it
    if phone and not user.get('phone'):
        user = db.update_user_phone(user['id'], phone)

    token = db.create_session(user['id'])
    donor = db.get_donor_by_user_id(user['id'])

    user_profile = donor if donor else {
        "id": user["id"],
        "phone": user.get("phone"),
        "email": user.get("email"),
        "name": donor.get("name") if donor else (user.get("oauth_name") or name or "User"),
        "picture": user.get("oauth_picture") or picture,
        "isNew": is_new or (donor is None)
    }

    return jsonify({
        "token": token,
        "user": user_profile,
        "isNew": is_new,
        "hasDonorProfile": donor is not None
    }), 200

@app.route('/api/auth/signup', methods=['POST'])
def auth_signup():
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    pin = (data.get('pin') or '').strip()
    turnstile_token = data.get('turnstile_token') or data.get('cf-turnstile-response')

    if not phone or len(phone) < 11:
        return jsonify({"error": "১১ ডিজিটের সঠিক মোবাইল নম্বর দিন"}), 400
    if not pin or len(pin) < 4:
        return jsonify({"error": "কমপক্ষে ৪ ডিজিটের পিন (PIN) দিন"}), 400

    # Verify Turnstile
    ok, err_msg = verify_turnstile(turnstile_token, request.remote_addr)
    if not ok:
        return jsonify({"error": err_msg, "turnstileFailed": True}), 400

    existing_user = db.get_user_by_phone(phone)
    existing_donor = db.get_donor_by_phone(phone)
    if existing_user or existing_donor:
        masked_name = mask_name(existing_donor['name']) if existing_donor and existing_donor.get("name") else ""
        name_info = f" ({masked_name})" if masked_name else ""
        return jsonify({
            "error": f"এই নম্বর দিয়ে ইতিমধ্যেই একজন রক্তদাতা{name_info} নিবন্ধিত আছেন। অনুগ্রহ করে লগইন করুন।",
            "alreadyRegistered": True,
            "name": masked_name
        }), 409

    user = db.create_user(phone, pin)
    token = db.create_session(user["id"])

    user_profile = {
        "id": user["id"],
        "phone": user["phone"],
        "name": "User",
        "isNew": True
    }
    return jsonify({"token": token, "user": user_profile}), 201

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    pin = (data.get('pin') or '').strip()
    turnstile_token = data.get('turnstile_token') or data.get('cf-turnstile-response')

    _, _, enabled = get_turnstile_config()
    if enabled:
        ok, err_msg = verify_turnstile(turnstile_token, request.remote_addr)
        if not ok:
            return jsonify({"error": err_msg, "turnstileFailed": True}), 400

    if not phone or not pin:
        return jsonify({"error": "মোবাইল নম্বর ও পিন প্রদান করুন"}), 400

    user = db.verify_user(phone, pin)
    if not user:
        return jsonify({"error": "Invalid login credentials / ভুল মোবাইল নম্বর অথবা পিন"}), 401

    token = db.create_session(user["id"])
    donor = db.get_donor_by_user_id(user["id"])

    user_profile = donor if donor else {
        "id": user["id"],
        "phone": user["phone"],
        "name": "User",
        "isNew": True
    }
    return jsonify({"token": token, "user": user_profile}), 200

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        db.delete_session(token)
    return jsonify({"success": True}), 200

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user = get_auth_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    donor = db.get_donor_by_user_id(user["id"])
    if donor:
        donor_profile = dict(donor)
        donor_profile['email'] = donor_profile.get('email') or user.get('email') or user.get('oauth_email')
        donor_profile['picture'] = donor_profile.get('picture') or user.get('oauth_picture')
        donor_profile['oauthProvider'] = user.get('oauth_provider')
        donor_profile['isNew'] = False
        return jsonify(donor_profile), 200

    display_name = user.get("name")
    if not display_name or display_name == "User":
        display_name = user.get("oauth_name") or (user.get("email").split('@')[0] if user.get("email") else "User")

    user_profile = {
        "id": user["id"],
        "phone": user.get("phone"),
        "email": user.get("email") or user.get("oauth_email"),
        "name": display_name,
        "picture": user.get("oauth_picture"),
        "oauthProvider": user.get("oauth_provider"),
        "isNew": True
    }
    return jsonify(user_profile), 200

# ── Donors Endpoints ──────────────────────────────────────────

@app.route('/api/donors/search', methods=['GET'])
def donors_search():
    blood_group = request.args.get('bloodGroup')
    district = request.args.get('district')
    upazila = request.args.get('upazila')
    area = request.args.get('area')
    availability = request.args.get('availability')

    results = db.search_donors(
        blood_group=blood_group,
        district=district,
        upazila=upazila,
        area=area,
        availability=availability
    )
    auth_user = get_auth_user()
    obfuscated = [obfuscate_donor(d, auth_user) for d in results]
    return jsonify(obfuscated), 200

@app.route('/api/donors', methods=['GET'])
def donors_list():
    donors = db.get_donors()
    auth_user = get_auth_user()
    obfuscated = [obfuscate_donor(d, auth_user) for d in donors]
    return jsonify(obfuscated), 200

@app.route('/api/donors', methods=['POST'])
def donors_create():
    body = request.get_json(silent=True) or {}
    phone = (body.get('phone') or '').strip()
    turnstile_token = body.get('turnstile_token') or body.get('cf-turnstile-response')

    auth_user = get_auth_user()
    _, _, turnstile_enabled = get_turnstile_config()
    if not auth_user and turnstile_enabled:
        ok, err_msg = verify_turnstile(turnstile_token, request.remote_addr)
        if not ok:
            return jsonify({"error": err_msg, "turnstileFailed": True}), 400

    if phone:
        existing_donor = db.get_donor_by_phone(phone)
        if existing_donor:
            masked_name = mask_name(existing_donor.get('name')) if existing_donor.get('name') else ""
            name_info = f" ({masked_name})" if masked_name else ""
            return jsonify({
                "error": f"এই ফোন নম্বরে ইতিমধ্যে একজন রক্তদাতা{name_info} নিবন্ধিত আছেন। অনুগ্রহ করে লগইন করুন।",
                "alreadyRegistered": True,
                "name": masked_name
            }), 409

    auth_user = get_auth_user()
    if auth_user:
        if not body.get('userId'):
            body['userId'] = auth_user['id']
        existing_user_donor = db.get_donor_by_user_id(auth_user['id'])
        if existing_user_donor:
            return jsonify({
                "error": "আপনার অ্যাকাউন্টে ইতিমধ্যে একজন রক্তদাতা প্রোফাইল নিবন্ধিত আছে।",
                "alreadyRegistered": True
            }), 409
        if phone and not auth_user.get('phone'):
            db.update_user_phone(auth_user['id'], phone)

    try:
        created = db.add_donor(body)
        return jsonify(created), 201
    except Exception as e:
        if 'UNIQUE constraint failed' in str(e):
            return jsonify({
                "error": "এই ফোন নম্বর বা অ্যাকাউন্টে ইতিমধ্যে রক্তদাতা নিবন্ধিত আছে।",
                "alreadyRegistered": True
            }), 409
        return jsonify({"error": str(e)}), 500

@app.route('/api/donors/<donor_id>', methods=['GET'])
def donors_detail(donor_id):
    donor = db.get_donor_by_id(donor_id)
    if not donor:
        return jsonify({"error": "Donor not found"}), 404
    auth_user = get_auth_user()
    return jsonify(obfuscate_donor(donor, auth_user)), 200

@app.route('/api/donors/<donor_id>', methods=['PUT'])
def donors_update(donor_id):
    auth_user = get_auth_user()
    if not auth_user:
        return jsonify({"error": "অনুমতি নেই / Unauthorized"}), 401
    
    donor = db.get_donor_by_id(donor_id)
    if not donor:
        return jsonify({"error": "Donor not found"}), 404
        
    donor_uid = donor.get('userId') or donor.get('user_id')
    donor_phone = donor.get('phone')
    if auth_user['id'] != donor_uid and auth_user['id'] != donor_id and auth_user.get('phone') != donor_phone:
        return jsonify({"error": "অনুমতি নেই: আপনি শুধুমাত্র নিজের প্রোফাইল পরিবর্তন করতে পারেন"}), 403

    body = request.get_json(silent=True) or {}
    # Prevent tampering with primary keys
    body.pop('id', None)
    body.pop('userId', None)
    body.pop('user_id', None)

    db.update_donor(donor_id, body)
    updated = db.get_donor_by_id(donor_id)
    return jsonify(updated or {"success": True}), 200

# ── Blood Requests Endpoints ──────────────────────────────────

@app.route('/api/requests', methods=['GET'])
def requests_list():
    reqs = db.get_requests()
    auth_user = get_auth_user()
    obfuscated = [obfuscate_request(r, auth_user) for r in reqs]
    return jsonify(obfuscated), 200

@app.route('/api/requests', methods=['POST'])
def requests_create():
    body = request.get_json(silent=True) or {}
    auth_user = get_auth_user()
    if auth_user and not body.get('userId'):
        body['userId'] = auth_user['id']
    created = db.add_request(body)
    return jsonify(created), 201

@app.route('/api/requests/<req_id>', methods=['PUT'])
def requests_update(req_id):
    body = request.get_json(silent=True) or {}
    db.update_request(req_id, body)
    updated = db.get_request_by_id(req_id)
    return jsonify(updated or {"success": True}), 200

# ── Contact Requests Endpoints ────────────────────────────────

@app.route('/api/contacts', methods=['GET'])
def contacts_list():
    auth_user = get_auth_user()
    if not auth_user:
        return jsonify({"error": "অনুমতি নেই / Unauthorized"}), 401
    contacts = db.get_contact_requests()
    user_donor = db.get_donor_by_user_id(auth_user['id'])
    donor_id = user_donor['id'] if user_donor else None
    filtered = [
        c for c in contacts 
        if c.get('userId') == auth_user['id'] or (donor_id and c.get('donorId') == donor_id)
    ]
    return jsonify(filtered), 200

@app.route('/api/contacts', methods=['POST'])
def contacts_create():
    body = request.get_json(silent=True) or {}
    auth_user = get_auth_user()
    if auth_user and not body.get('userId'):
        body['userId'] = auth_user['id']
    created = db.add_contact_request(body)
    return jsonify(created), 201

@app.route('/api/contacts/<contact_id>', methods=['PUT'])
def contacts_update(contact_id):
    body = request.get_json(silent=True) or {}
    db.update_contact_request(contact_id, body)
    updated = db.get_contact_request_by_id(contact_id)
    return jsonify(updated or {"success": True}), 200

# ═══════════════════════════════════════════════════════════════
# STATIC ASSETS & SPA ROUTING
# ═══════════════════════════════════════════════════════════════

def get_file_hash(rel_path: str) -> str:
    clean_rel = re.sub(r'^\.?/+', '', rel_path.split('?')[0])
    full_path = os.path.normpath(os.path.join(ROOT_DIR, clean_rel))
    try:
        if os.path.isfile(full_path):
            return hex(int(os.path.getmtime(full_path)))[2:]
    except Exception:
        pass
    return hex(int(time.time()))[2:]

def process_html(content: str) -> str:
    # 1. Inject fresh file-hash query strings
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

    # 2. Inject anti-cache meta tags if missing
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
def serve_static(path):
    # Reject unresolved /api/ routes
    if path.startswith('api/'):
        return jsonify({"error": "API route not found"}), 404

    full_path = os.path.join(ROOT_DIR, path)

    # If file exists and is not a directory
    if path and os.path.isfile(full_path):
        if path.endswith('.html'):
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return Response(process_html(content), mimetype='text/html; charset=utf-8')
            except Exception:
                pass
        return send_from_directory(ROOT_DIR, path)

    # SPA Fallback: serve index.html with cache-busting
    index_path = os.path.join(ROOT_DIR, 'index.html')
    if os.path.isfile(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return Response(process_html(content), mimetype='text/html; charset=utf-8')
        except Exception:
            return send_from_directory(ROOT_DIR, 'index.html')

    return "<h1>404 — File Not Found</h1>", 404

if __name__ == '__main__':
    local_url = f"http://localhost:{port}"
    net_url = f"http://127.0.0.1:{port}"

    print("\n" + "=" * 64)
    print(f"{C_BRIGHT}{C_RED}  🩸 RENEWAL BLOOD NETWORK — PYTHON SERVER RUNNING{C_RESET}")
    print("=" * 64)
    print(f"  {C_GREEN}● Local Access:{C_RESET}    {C_CYAN}{local_url}{C_RESET}")
    print(f"  {C_GREEN}● Network Access:{C_RESET}  {C_CYAN}{net_url}{C_RESET}")
    print(f"  {C_GREEN}● Port:{C_RESET}            {C_BRIGHT}{port}{C_RESET}")
    print(f"  {C_GREEN}● Root Directory:{C_RESET}  {ROOT_DIR}")
    print(f"  {C_GREEN}● Database:{C_RESET}        MySQL/MariaDB ({getattr(db, 'DB_NAME', 'renewal_blood')})")
    print(f"  {C_GREEN}● Engine:{C_RESET}          Python 3 + Flask + PyMySQL")
    print("=" * 64 + "\n")

    app.run(host=HOST, port=port, threaded=True, debug=False)

