"""
==============================================================================
RENEWAL BLOOD NETWORK — Database Module (MySQL / MariaDB via PyMySQL)
==============================================================================
Pure MySQL/MariaDB database adapter for Renewal Blood Network.
Shared by server.py (port 5500) and admin/server.py (port 8081).
Features:
 - Thread-safe PyMySQL DictCursor connections
 - Seamless parameter binding (? and %s) with query safety
 - Atomic version tracking for real-time WebSocket sync
 - Production-grade schema definitions with foreign keys and indexes
==============================================================================
"""

import os
import hashlib
import secrets
import json
import time
from datetime import datetime, timedelta, timezone
import pymysql
import pymysql.cursors

# ── Load Environment Configuration ────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_env():
    env_file = os.path.join(ROOT_DIR, '.env')
    if os.path.isfile(env_file):
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass

_load_env()

DB_TYPE = os.environ.get('DB_TYPE', 'mysql').lower()
DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
DB_PORT = int(os.environ.get('DB_PORT', 3306))
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'renewal_blood')


# ── MySQL / MariaDB Wrappers ──────────────────────────────────
class MySQLCursorWrapper:
    """Wraps PyMySQL cursor to provide parameter compatibility (? -> %s) and clean mapping."""
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def execute(self, sql, params=None):
        mysql_sql = sql.replace('?', '%s')
        mysql_sql = mysql_sql.replace("datetime('now')", "NOW()").replace('datetime("now")', "NOW()")
        if "ON CONFLICT" in mysql_sql and "oauth_accounts" in mysql_sql:
            mysql_sql = """
                INSERT INTO oauth_accounts (id, user_id, provider, provider_user_id, email, name, picture)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    user_id = VALUES(user_id),
                    email = VALUES(email),
                    name = VALUES(name),
                    picture = VALUES(picture)
            """
        if params is None:
            self._cur.execute(mysql_sql)
        else:
            if isinstance(params, list):
                params = tuple(params)
            self._cur.execute(mysql_sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class MySQLConnectionWrapper:
    """Wraps PyMySQL connection to provide execute(), cursor() and context-manager commit/rollback."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return MySQLCursorWrapper(self._conn.cursor(pymysql.cursors.DictCursor))

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()


# ── Database Connection Factory ───────────────────────────────
def get_db():
    """Create and return a thread-safe connection to MariaDB / MySQL."""
    raw = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        autocommit=False,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )
    return MySQLConnectionWrapper(raw)


# ── Real-Time Sync & Data Versioning ──────────────────────────
def bump_data_version():
    """Bumps the data version whenever new data is created or updated."""
    try:
        conn = get_db()
        with conn:
            conn.execute("""
                INSERT INTO meta (mkey, mval) VALUES ('data_version', '1')
                ON DUPLICATE KEY UPDATE mval = CAST(mval AS UNSIGNED) + 1
            """)
        conn.close()
    except Exception as e:
        print(f"[DB Warning] bump_data_version failed: {e}")

def get_data_version():
    """Returns a unique version string that changes whenever the database is updated."""
    try:
        conn = get_db()
        row = conn.execute("SELECT mval, UNIX_TIMESTAMP(updated_at) as ts FROM meta WHERE mkey = 'data_version'").fetchone()
        conn.close()
        if row:
            return f"{row['mval']}_{row.get('ts') or int(time.time())}"
    except Exception as e:
        print(f"[DB Warning] get_data_version failed: {e}")
    return str(int(time.time() * 1000))


# ── Database Schema Initialization ────────────────────────────
def init_db():
    """Create all tables and indexes if they do not exist in MySQL/MariaDB."""
    try:
        conn = get_db()
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY,
                phone VARCHAR(32) UNIQUE,
                email VARCHAR(255),
                pwd_hash VARCHAR(255),
                pwd_salt VARCHAR(255),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_users_email (email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_accounts (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                provider VARCHAR(32) NOT NULL,
                provider_user_id VARCHAR(128) NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                picture TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_provider_user (provider, provider_user_id),
                INDEX idx_oauth_user_id (user_id),
                CONSTRAINT fk_oauth_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token VARCHAR(128) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_sessions_user_id (user_id),
                CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS donors (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64),
                name VARCHAR(255),
                name_en VARCHAR(255),
                phone VARCHAR(32) UNIQUE,
                alt_phone VARCHAR(32),
                blood_group VARCHAR(16),
                district VARCHAR(128),
                upazila VARCHAR(128),
                area VARCHAR(255),
                age INT,
                gender VARCHAR(32),
                profession VARCHAR(255),
                last_donation VARCHAR(64),
                donation_count INT DEFAULT 0,
                can_donate TINYINT(1) DEFAULT 1,
                next_available VARCHAR(64),
                donation_types LONGTEXT,
                emergency_call TINYINT(1) DEFAULT 0,
                contact_prefs LONGTEXT,
                verification_level INT DEFAULT 0,
                trust_score INT DEFAULT 0,
                badge VARCHAR(64) DEFAULT 'registered',
                availability VARCHAR(64) DEFAULT 'available',
                donation_history LONGTEXT,
                verification_log LONGTEXT,
                join_date VARCHAR(64),
                suspicious TINYINT(1) DEFAULT 0,
                reported INT DEFAULT 0,
                lat DOUBLE,
                lng DOUBLE,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_donors_user_id (user_id),
                INDEX idx_donors_blood_group (blood_group),
                INDEX idx_donors_district (district),
                INDEX idx_donors_availability (availability),
                INDEX idx_donors_trust_score (trust_score),
                CONSTRAINT fk_donors_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS blood_requests (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64),
                patient_name VARCHAR(255),
                blood_group VARCHAR(16),
                units INT DEFAULT 1,
                hospital VARCHAR(255),
                district VARCHAR(128),
                upazila VARCHAR(128),
                needed_date VARCHAR(64),
                needed_time VARCHAR(64),
                attendant_name VARCHAR(255),
                contact VARCHAR(64),
                reason TEXT,
                status VARCHAR(64) DEFAULT 'pending',
                submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                verified_at DATETIME,
                reported INT DEFAULT 0,
                verification_note TEXT,
                INDEX idx_requests_status (status),
                CONSTRAINT fk_requests_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64),
                donor_id VARCHAR(64) NOT NULL,
                patient VARCHAR(255),
                blood_group VARCHAR(16),
                hospital VARCHAR(255),
                units INT DEFAULT 1,
                phone VARCHAR(64),
                status VARCHAR(64) DEFAULT 'pending',
                submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_contact_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                CONSTRAINT fk_contact_donor FOREIGN KEY (donor_id) REFERENCES donors(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                mkey VARCHAR(64) PRIMARY KEY,
                mval TEXT,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        conn.close()
    except Exception as e:
        print(f"[DB Error] Failed initializing MariaDB/MySQL: {e}")

# Auto-initialize database schema on module load
init_db()

# ── Helpers ───────────────────────────────────────────────────
def generate_id(prefix=''):
    """Generate unique prefixed alphanumeric ID."""
    t_part = hex(int(time.time() * 1000))[2:].upper()
    r_part = secrets.token_hex(2).upper()
    return f"{prefix}{t_part}{r_part}"

def to_json(val):
    if val is None:
        return '[]'
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False)

def from_json(val, fallback=None):
    if fallback is None:
        fallback = []
    if not val:
        return fallback
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return fallback

# ── Password Hashing ──────────────────────────────────────────
def hash_password(pin: str, salt: str) -> str:
    """Matches Node.js crypto.scryptSync(pin + 'RenewalSec!', salt, 64).toString('hex')"""
    pwd = (str(pin) + 'RenewalSec!').encode('utf-8')
    s = salt.encode('utf-8')
    return hashlib.scrypt(pwd, salt=s, n=16384, r=8, p=1, maxmem=0, dklen=64).hex()

def create_salt() -> str:
    return secrets.token_hex(16)

# ── Trust Score Calculation ───────────────────────────────────
def calc_trust_score(donor) -> int:
    score = 0
    if not isinstance(donor, dict):
        donor = dict(donor)
    level = donor.get("verificationLevel", donor.get("verification_level", 0)) or 0
    if level >= 1: score += 15
    if level >= 2: score += 20
    if level >= 3: score += 25
    if level >= 4: score += 20
    count = donor.get("donationCount", donor.get("donation_count", 0)) or 0
    score += min(count, 10) * 2
    rep = donor.get("reported", 0) or 0
    if not rep: score += 5
    return min(score, 100)

# ── Row Mappers ───────────────────────────────────────────────
def map_donor(row):
    if not row:
        return None
    d = dict(row)
    return {
        "id": d["id"],
        "userId": d.get("user_id"),
        "name": d.get("name"),
        "nameEn": d.get("name_en"),
        "phone": d.get("phone"),
        "altPhone": d.get("alt_phone"),
        "bloodGroup": d.get("blood_group"),
        "district": d.get("district"),
        "upazila": d.get("upazila"),
        "area": d.get("area"),
        "age": d.get("age"),
        "gender": d.get("gender"),
        "profession": d.get("profession"),
        "lastDonation": d.get("last_donation"),
        "donationCount": d.get("donation_count") if d.get("donation_count") is not None else 0,
        "canDonate": bool(d.get("can_donate")),
        "nextAvailable": d.get("next_available"),
        "donationTypes": from_json(d.get("donation_types"), []),
        "emergencyCall": bool(d.get("emergency_call")),
        "contactPrefs": from_json(d.get("contact_prefs"), []),
        "verificationLevel": d.get("verification_level") if d.get("verification_level") is not None else 0,
        "trustScore": d.get("trust_score") if d.get("trust_score") is not None else 0,
        "badge": d.get("badge") or "registered",
        "availability": d.get("availability") or "available",
        "donationHistory": from_json(d.get("donation_history"), []),
        "verificationLog": from_json(d.get("verification_log"), []),
        "joinDate": d.get("join_date"),
        "suspicious": bool(d.get("suspicious")),
        "reported": d.get("reported") or 0,
        "lat": d.get("lat"),
        "lng": d.get("lng"),
    }

def map_request(row):
    if not row:
        return None
    d = dict(row)
    sub_at = d.get("submitted_at")
    if isinstance(sub_at, datetime):
        sub_at = sub_at.strftime("%Y-%m-%d %H:%M:%S")
    ver_at = d.get("verified_at")
    if isinstance(ver_at, datetime):
        ver_at = ver_at.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": d["id"],
        "userId": d.get("user_id"),
        "patientName": d.get("patient_name"),
        "bloodGroup": d.get("blood_group"),
        "units": d.get("units"),
        "hospital": d.get("hospital"),
        "district": d.get("district"),
        "upazila": d.get("upazila"),
        "neededDate": d.get("needed_date"),
        "neededTime": d.get("needed_time"),
        "attendantName": d.get("attendant_name"),
        "contact": d.get("contact"),
        "reason": d.get("reason"),
        "status": d.get("status") or "pending",
        "submittedAt": sub_at,
        "verifiedAt": ver_at,
        "reported": d.get("reported") or 0,
        "verificationNote": d.get("verification_note") or "",
    }

def map_contact_request(row):
    if not row:
        return None
    d = dict(row)
    sub_at = d.get("submitted_at")
    if isinstance(sub_at, datetime):
        sub_at = sub_at.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": d["id"],
        "userId": d.get("user_id"),
        "donorId": d.get("donor_id"),
        "patient": d.get("patient"),
        "bloodGroup": d.get("blood_group"),
        "hospital": d.get("hospital"),
        "units": d.get("units"),
        "phone": d.get("phone"),
        "status": d.get("status") or "pending",
        "submittedAt": sub_at,
    }

# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

def create_user(phone: str, pin: str):
    salt = create_salt()
    pwd_hash = hash_password(pin, salt)
    user_id = generate_id('USR')
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO users (id, phone, pwd_hash, pwd_salt) VALUES (?, ?, ?, ?)",
            (user_id, phone, pwd_hash, salt)
        )
    conn.close()
    bump_data_version()
    return {"id": user_id, "phone": phone}

def verify_user(phone: str, pin: str):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    if not user:
        return None
    user_dict = dict(user)
    calc_hash = hash_password(pin, user_dict["pwd_salt"])
    if calc_hash != user_dict["pwd_hash"]:
        return None
    return user_dict

def get_user_by_id(user_id: str):
    if not user_id:
        return None
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.phone, u.email, u.created_at,
               oa.provider as oauth_provider,
               oa.provider_user_id as oauth_provider_user_id,
               oa.name as oauth_name,
               oa.picture as oauth_picture,
               oa.email as oauth_email
        FROM users u
        LEFT JOIN oauth_accounts oa ON oa.user_id = u.id
        WHERE u.id = ?
    """, (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    if not d.get('email') and d.get('oauth_email'):
        d['email'] = d['oauth_email']
    if d.get('oauth_name'):
        d['name'] = d['oauth_name']
    elif d.get('email'):
        d['name'] = d['email'].split('@')[0]
    else:
        d['name'] = d.get('phone') or 'User'
    return d

def get_user_by_phone(phone: str):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return dict(user) if user else None

def create_session(user_id: str) -> str:
    token = secrets.token_hex(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at)
        )
    conn.close()
    return token

def get_session_user(token: str):
    if not token:
        return None
    conn = get_db()
    session = conn.execute(
        "SELECT * FROM sessions WHERE token = ? AND expires_at > NOW()",
        (token,)
    ).fetchone()
    conn.close()
    if not session:
        return None
    return get_user_by_id(session["user_id"])

def delete_session(token: str):
    if not token:
        return
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.close()

# ── OAuth Helpers ─────────────────────────────────────────────

def get_user_by_oauth(provider: str, provider_user_id: str):
    """Find user profile by OAuth provider and provider unique user ID."""
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.phone, u.email, u.created_at,
               oa.provider, oa.provider_user_id, oa.name as oauth_name, oa.picture as oauth_picture
        FROM oauth_accounts oa
        JOIN users u ON u.id = oa.user_id
        WHERE oa.provider = ? AND oa.provider_user_id = ?
    """, (provider, provider_user_id)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    d['name'] = d.get('oauth_name') or (d.get('email').split('@')[0] if d.get('email') else 'User')
    return d

def get_user_by_email(email: str):
    """Find user by email address."""
    if not email:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(user) if user else None

def create_oauth_user(provider: str, provider_user_id: str, email: str = None, name: str = None, picture: str = None, phone: str = None):
    """Creates a new user record linked to an OAuth provider (e.g. Google)."""
    user_id = generate_id('USR')
    oauth_id = generate_id('OA')
    clean_email = email.lower().strip() if email else None
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO users (id, phone, email, pwd_hash, pwd_salt) VALUES (?, ?, ?, NULL, NULL)",
            (user_id, phone, clean_email)
        )
        conn.execute(
            "INSERT INTO oauth_accounts (id, user_id, provider, provider_user_id, email, name, picture) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (oauth_id, user_id, provider, provider_user_id, clean_email, name, picture)
        )
    conn.close()
    bump_data_version()
    return {
        "id": user_id,
        "phone": phone,
        "email": clean_email,
        "name": name,
        "picture": picture,
        "isNew": True
    }

def link_oauth_account(user_id: str, provider: str, provider_user_id: str, email: str = None, name: str = None, picture: str = None):
    """Links an OAuth provider account to an existing user."""
    oauth_id = generate_id('OA')
    clean_email = email.lower().strip() if email else None
    conn = get_db()
    with conn:
        if clean_email:
            conn.execute("UPDATE users SET email = COALESCE(email, ?) WHERE id = ?", (clean_email, user_id))
        conn.execute("""
            INSERT INTO oauth_accounts (id, user_id, provider, provider_user_id, email, name, picture)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                email = VALUES(email),
                name = VALUES(name),
                picture = VALUES(picture)
        """, (oauth_id, user_id, provider, provider_user_id, clean_email, name, picture))
    conn.close()
    bump_data_version()
    return get_user_by_id(user_id)

def update_user_phone(user_id: str, phone: str):
    """Update phone for a user (e.g. after Google sign-in onboarding)."""
    conn = get_db()
    with conn:
        conn.execute("UPDATE users SET phone = ? WHERE id = ?", (phone.strip(), user_id))
    conn.close()
    bump_data_version()
    return get_user_by_id(user_id)

# ═══════════════════════════════════════════════════════════════
# DONORS
# ═══════════════════════════════════════════════════════════════

def get_donors():
    conn = get_db()
    rows = conn.execute("SELECT * FROM donors ORDER BY trust_score DESC").fetchall()
    conn.close()
    return [map_donor(r) for r in rows]

def get_donor_by_id(donor_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM donors WHERE id = ?", (donor_id,)).fetchone()
    conn.close()
    return map_donor(row)

def get_donor_by_user_id(user_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM donors WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return map_donor(row)

def get_donor_by_phone(phone: str):
    if not phone:
        return None
    conn = get_db()
    p = phone.strip()
    row = conn.execute("SELECT * FROM donors WHERE phone = ? OR alt_phone = ?", (p, p)).fetchone()
    conn.close()
    return map_donor(row)

def search_donors(blood_group=None, district=None, upazila=None, area=None, availability=None):
    sql = "SELECT * FROM donors WHERE 1=1"
    params = []
    if blood_group:
        sql += " AND blood_group = ?"
        params.append(blood_group)
    if district:
        sql += " AND district = ?"
        params.append(district)
    if upazila:
        sql += " AND upazila = ?"
        params.append(upazila)
    if area:
        sql += " AND area LIKE ?"
        params.append(f"%{area}%")
    if availability == "available":
        sql += " AND availability = ?"
        params.append("available")
    elif availability == "soon":
        sql += " AND availability IN (?, ?)"
        params.extend(["available", "soon"])

    sql += " ORDER BY trust_score DESC"
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [map_donor(r) for r in rows]

def add_donor(donor: dict):
    donor_id = donor.get("id") or generate_id('DNR')
    
    t_score = donor.get("trustScore")
    if t_score is None:
        t_score = donor.get("trust_score")
    if t_score is None:
        t_score = calc_trust_score(donor)

    can_donate_val = donor.get("canDonate")
    if can_donate_val is None:
        can_donate_val = donor.get("can_donate", 1)
    can_donate_int = 1 if can_donate_val else 0

    emergency_call_val = donor.get("emergencyCall") or donor.get("emergency_call") or 0
    emergency_call_int = 1 if emergency_call_val else 0

    suspicious_val = donor.get("suspicious") or 0
    suspicious_int = 1 if suspicious_val else 0

    conn = get_db()
    with conn:
        conn.execute("""
            INSERT INTO donors (
                id, user_id, name, name_en, phone, alt_phone, blood_group,
                district, upazila, area, age, gender, profession,
                last_donation, donation_count, can_donate, next_available,
                donation_types, emergency_call, contact_prefs,
                verification_level, trust_score, badge, availability,
                donation_history, verification_log, join_date,
                suspicious, reported, lat, lng
            ) VALUES (
                ?,?,?,?,?,?,?,
                ?,?,?,?,?,?,
                ?,?,?,?,
                ?,?,?,
                ?,?,?,?,
                ?,?,?,
                ?,?,?,?
            )
        """, (
            donor_id,
            donor.get("userId") or donor.get("user_id"),
            donor.get("name"),
            donor.get("nameEn") or donor.get("name_en"),
            donor.get("phone"),
            donor.get("altPhone") or donor.get("alt_phone"),
            donor.get("bloodGroup") or donor.get("blood_group"),
            donor.get("district"),
            donor.get("upazila"),
            donor.get("area"),
            donor.get("age"),
            donor.get("gender"),
            donor.get("profession"),
            donor.get("lastDonation") or donor.get("last_donation"),
            donor.get("donationCount") or donor.get("donation_count") or 0,
            can_donate_int,
            donor.get("nextAvailable") or donor.get("next_available"),
            to_json(donor.get("donationTypes") or donor.get("donation_types")),
            emergency_call_int,
            to_json(donor.get("contactPrefs") or donor.get("contact_prefs")),
            donor.get("verificationLevel") or donor.get("verification_level") or 0,
            t_score,
            donor.get("badge") or "registered",
            donor.get("availability") or "available",
            to_json(donor.get("donationHistory") or donor.get("donation_history")),
            to_json(donor.get("verificationLog") or donor.get("verification_log")),
            donor.get("joinDate") or donor.get("join_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            suspicious_int,
            donor.get("reported") or 0,
            donor.get("lat"),
            donor.get("lng")
        ))
    conn.close()
    bump_data_version()
    return get_donor_by_id(donor_id)

def update_donor(donor_id: str, updates: dict):
    key_map = {
        "name": "name", "nameEn": "name_en", "phone": "phone", "altPhone": "alt_phone",
        "bloodGroup": "blood_group", "district": "district", "upazila": "upazila",
        "area": "area", "age": "age", "gender": "gender", "profession": "profession",
        "lastDonation": "last_donation", "donationCount": "donation_count",
        "canDonate": "can_donate", "nextAvailable": "next_available",
        "donationTypes": "donation_types", "emergencyCall": "emergency_call",
        "contactPrefs": "contact_prefs", "verificationLevel": "verification_level",
        "trustScore": "trust_score", "badge": "badge", "availability": "availability",
        "donationHistory": "donation_history", "verificationLog": "verification_log",
        "joinDate": "join_date", "suspicious": "suspicious", "reported": "reported",
        "lat": "lat", "lng": "lng",
        "name_en": "name_en", "alt_phone": "alt_phone", "blood_group": "blood_group",
        "last_donation": "last_donation", "donation_count": "donation_count",
        "can_donate": "can_donate", "next_available": "next_available",
        "donation_types": "donation_types", "emergency_call": "emergency_call",
        "contact_prefs": "contact_prefs", "verification_level": "verification_level",
        "trust_score": "trust_score", "donation_history": "donation_history",
        "verification_log": "verification_log", "join_date": "join_date",
    }
    json_cols = {"donation_types", "contact_prefs", "donation_history", "verification_log"}
    bool_cols = {"can_donate", "emergency_call", "suspicious"}

    set_clauses = []
    params = []

    for k, v in updates.items():
        if v is None and k not in ("nextAvailable", "next_available", "lastDonation", "last_donation"):
            continue
        col = key_map.get(k, k)
        val = v
        if col in json_cols:
            val = to_json(v)
        elif col in bool_cols:
            val = 1 if v else 0
        set_clauses.append(f"{col} = ?")
        params.append(val)

    has_verif_change = "verificationLevel" in updates or "verification_level" in updates
    has_explicit_score = "trustScore" in updates or "trust_score" in updates
    if has_verif_change and not has_explicit_score:
        conn = get_db()
        existing = conn.execute("SELECT * FROM donors WHERE id = ?", (donor_id,)).fetchone()
        conn.close()
        if existing:
            merged = dict(existing)
            merged["verificationLevel"] = updates.get("verificationLevel", updates.get("verification_level"))
            set_clauses.append("trust_score = ?")
            params.append(calc_trust_score(merged))

    if not set_clauses:
        return

    params.append(donor_id)
    conn = get_db()
    with conn:
        conn.execute(f"UPDATE donors SET {', '.join(set_clauses)} WHERE id = ?", params)
    conn.close()
    bump_data_version()

# ═══════════════════════════════════════════════════════════════
# BLOOD REQUESTS
# ═══════════════════════════════════════════════════════════════

def get_requests():
    conn = get_db()
    rows = conn.execute("SELECT * FROM blood_requests ORDER BY submitted_at DESC").fetchall()
    conn.close()
    return [map_request(r) for r in rows]

def get_request_by_id(request_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM blood_requests WHERE id = ?", (request_id,)).fetchone()
    conn.close()
    return map_request(row)

def add_request(req: dict):
    req_id = req.get("id") or generate_id('REQ')
    units = 1
    try:
        units = int(req.get("units", 1))
    except (ValueError, TypeError):
        pass

    now_val = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    with conn:
        conn.execute("""
            INSERT INTO blood_requests (
                id, user_id, patient_name, blood_group, units, hospital,
                district, upazila, needed_date, needed_time, attendant_name,
                contact, reason, status, submitted_at, verified_at,
                reported, verification_note
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            req_id,
            req.get("userId") or req.get("user_id"),
            req.get("patientName") or req.get("patient_name"),
            req.get("bloodGroup") or req.get("blood_group"),
            units,
            req.get("hospital"),
            req.get("district"),
            req.get("upazila"),
            req.get("neededDate") or req.get("needed_date"),
            req.get("neededTime") or req.get("needed_time"),
            req.get("attendantName") or req.get("attendant_name"),
            req.get("contact"),
            req.get("reason"),
            req.get("status") or "pending",
            req.get("submittedAt") or req.get("submitted_at") or now_val,
            req.get("verifiedAt") or req.get("verified_at"),
            req.get("reported") or 0,
            req.get("verificationNote") or req.get("verification_note") or ""
        ))
    conn.close()
    bump_data_version()
    return get_request_by_id(req_id)

def update_request(request_id: str, updates: dict):
    key_map = {
        "patientName": "patient_name", "bloodGroup": "blood_group", "units": "units",
        "hospital": "hospital", "district": "district", "upazila": "upazila",
        "neededDate": "needed_date", "neededTime": "needed_time",
        "attendantName": "attendant_name", "contact": "contact", "reason": "reason",
        "status": "status", "submittedAt": "submitted_at", "verifiedAt": "verified_at",
        "reported": "reported", "verificationNote": "verification_note",
        "patient_name": "patient_name", "blood_group": "blood_group",
        "needed_date": "needed_date", "needed_time": "needed_time",
        "attendant_name": "attendant_name", "submitted_at": "submitted_at",
        "verified_at": "verified_at", "verification_note": "verification_note",
    }
    set_clauses = []
    params = []
    for k, v in updates.items():
        if v is None and k not in ("verifiedAt", "verified_at", "neededDate", "needed_date"):
            continue
        col = key_map.get(k, k)
        set_clauses.append(f"{col} = ?")
        params.append(v)

    if not set_clauses:
        return
    params.append(request_id)
    conn = get_db()
    with conn:
        conn.execute(f"UPDATE blood_requests SET {', '.join(set_clauses)} WHERE id = ?", params)
    conn.close()
    bump_data_version()

# ═══════════════════════════════════════════════════════════════
# CONTACT REQUESTS
# ═══════════════════════════════════════════════════════════════

def get_contact_requests():
    conn = get_db()
    rows = conn.execute("SELECT * FROM contact_requests ORDER BY submitted_at DESC").fetchall()
    conn.close()
    return [map_contact_request(r) for r in rows]

def get_contact_request_by_id(contact_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM contact_requests WHERE id = ?", (contact_id,)).fetchone()
    conn.close()
    return map_contact_request(row)

def add_contact_request(req: dict):
    req_id = req.get("id") or generate_id('CON')
    units = 1
    try:
        units = int(req.get("units", 1))
    except (ValueError, TypeError):
        pass

    now_val = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    with conn:
        conn.execute("""
            INSERT INTO contact_requests (
                id, user_id, donor_id, patient, blood_group,
                hospital, units, phone, status, submitted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            req_id,
            req.get("userId") or req.get("user_id"),
            req.get("donorId") or req.get("donor_id"),
            req.get("patient"),
            req.get("bloodGroup") or req.get("blood_group"),
            req.get("hospital"),
            units,
            req.get("phone"),
            req.get("status") or "pending",
            req.get("submittedAt") or req.get("submitted_at") or now_val
        ))
    conn.close()
    bump_data_version()
    return get_contact_request_by_id(req_id)

def update_contact_request(contact_id: str, updates: dict):
    key_map = {
        "donorId": "donor_id", "patient": "patient", "bloodGroup": "blood_group",
        "hospital": "hospital", "units": "units", "phone": "phone",
        "status": "status", "submittedAt": "submitted_at",
        "donor_id": "donor_id", "blood_group": "blood_group", "submitted_at": "submitted_at",
    }
    set_clauses = []
    params = []
    for k, v in updates.items():
        if v is None:
            continue
        col = key_map.get(k, k)
        set_clauses.append(f"{col} = ?")
        params.append(v)

    if not set_clauses:
        return
    params.append(contact_id)
    conn = get_db()
    with conn:
        conn.execute(f"UPDATE contact_requests SET {', '.join(set_clauses)} WHERE id = ?", params)
    conn.close()
    bump_data_version()
