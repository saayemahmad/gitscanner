/* ============================================================
   RENEWAL BLOOD NETWORK — Data Store (MySQL / MariaDB REST API)
   ============================================================
   Replaces the Supabase-based DataStore with a pure REST API
   client. All DataStore methods remain async with identical
   signatures — no changes required in any other JS module.

   Auth token stored in localStorage('rbn_token').
   API base: same origin (port 5500) — all routes /api/*
   ============================================================ */

/* ── Bangladesh Districts & Upazilas (static — unchanged) ── */
const BD_LOCATIONS = {
  'ঢাকা': ['সাভার','ধামরাই','কেরানীগঞ্জ','নবাবগঞ্জ','দোহার','মিরপুর','উত্তরা','গুলশান','বাড্ডা','মতিঝিল'],
  'গাজীপুর': ['টঙ্গী','গাজীপুর সদর','কালিগঞ্জ','কালীয়াকৈর','কাপাসিয়া','শ্রীপুর'],
  'নারায়ণগঞ্জ': ['নারায়ণগঞ্জ সদর','আড়াইহাজার','বন্দর','রূপগঞ্জ','সোনারগাঁও'],
  'চট্টগ্রাম': ['চট্টগ্রাম সদর','হাটহাজারী','পটিয়া','সীতাকুণ্ড','মিরসরাই','রাউজান','বোয়ালখালী','আনোয়ারা'],
  'সিলেট': ['সিলেট সদর','বিশ্বনাথ','জকিগঞ্জ','কোম্পানীগঞ্জ','গোয়াইনঘাট','বালাগঞ্জ'],
  'রাজশাহী': ['রাজশাহী সদর','বোয়ালিয়া','পবা','মোহনপুর','বাগমারা','তানোর'],
  'খুলনা': ['খুলনা সদর','সোনাডাঙ্গা','খালিশপুর','ডুমুরিয়া','বটিয়াঘাটা','ফুলতলা'],
  'বরিশাল': ['বরিশাল সদর','বাকেরগঞ্জ','বাবুগঞ্জ','উজিরপুর','মেহেন্দিগঞ্জ'],
  'ময়মনসিংহ': ['ময়মনসিংহ সদর','ভালুকা','ত্রিশাল','গফরগাঁও','মুক্তাগাছা'],
  'রংপুর': ['রংপুর সদর','গঙ্গাচড়া','তারাগঞ্জ','বদরগঞ্জ','মিঠাপুকুর'],
  'কুমিল্লা': ['কুমিল্লা সদর','দেবিদ্বার','বুড়িচং','চান্দিনা','দাউদকান্দি','লাকসাম'],
  'ফরিদপুর': ['ফরিদপুর সদর','নগরকান্দা','ভাঙ্গা','সালথা','আলফাডাঙ্গা'],
};

const BLOOD_GROUPS   = ['A+','A-','B+','B-','O+','O-','AB+','AB-'];
const DONATION_TYPES = ['সম্পূর্ণ রক্ত (Whole Blood)','প্লাটেলেট (Platelet)','প্লাজমা (Plasma)','লাল রক্তকণিকা (RBC)'];
const CONTACT_PREFS  = ['phone','sms','whatsapp','renewal'];

/* ── Auth token helpers ──────────────────────────────────────── */
const _getToken = () => localStorage.getItem('rbn_token');
const _setToken = (t) => {
  if (t) localStorage.setItem('rbn_token', t);
  else   localStorage.removeItem('rbn_token');
};

/* ── Auth state ──────────────────────────────────────────────── */
let _currentUser    = null;
const _authCallbacks = [];

/* ── REST API fetch helper ───────────────────────────────────── */
async function _api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const token = _getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(path, opts);

  if (!res.ok) {
    let errMsg = res.statusText;
    try {
      const json = await res.json();
      errMsg = json.error || json.message || errMsg;
    } catch (_) {}
    const err = new Error(errMsg);
    err.status = res.status;
    throw err;
  }

  // 204 No Content — return null
  if (res.status === 204) return null;
  return res.json();
}

/* ── Column name mapper: DB snake_case → app camelCase ── */
function _mapDonor(row) {
  if (!row) return null;
  // Server already returns camelCase from db.js mapDonor()
  // but keep this for safety/compatibility
  return row;
}

function _mapRequest(row)        { return row; }
function _mapContactRequest(row) { return row; }

/* ── DataStore ─────────────────────────────────────────────── */
const DataStore = {

  /* ── Server Config Cache (Turnstile, etc) ── */
  config: null,

  /* ── Initialise (restore session if token exists) ── */
  async init() {
    try {
      this.config = await _api('GET', '/api/config');
    } catch (e) {
      this.config = { turnstileSiteKey: '1x00000000000000000000AA', turnstileEnabled: true };
    }

    const token = _getToken();
    if (!token) return;
    try {
      _currentUser = await _api('GET', '/api/auth/me');
      console.log('[DataStore] Session restored for:', _currentUser?.phone || _currentUser?.id);
    } catch (e) {
      console.warn('[DataStore] Session restore failed — clearing token.', e.message);
      _setToken(null);
      _currentUser = null;
    }
  },

  /* ── WebSocket Real-Time Engine ── */
  _ws: null,
  _wsConnecting: false,
  _wsReconnectTimer: null,
  _wsReconnectDelay: 1000,
  _lastDataVersion: null,
  _realtimeCallbacks: [],
  _isPageHidden: false,
  _lifecycleInitialized: false,

  subscribeToChanges(callback) {
    if (typeof callback === 'function') {
      this._realtimeCallbacks.push(callback);
    }
    this._setupLifecycleListeners();
    if (!this._ws && !this._wsConnecting) {
      this.initWebSocket();
    }
  },

  _setupLifecycleListeners() {
    if (this._lifecycleInitialized) return;
    this._lifecycleInitialized = true;

    // Cleanly close WebSocket before page enters bfcache
    window.addEventListener('pagehide', (e) => {
      this._isPageHidden = true;
      clearTimeout(this._wsReconnectTimer);
      if (this._pingInterval) {
        clearInterval(this._pingInterval);
        this._pingInterval = null;
      }
      if (this._ws) {
        try {
          this._ws.close(1000, 'Page entered bfcache');
        } catch (_) {}
        this._ws = null;
      }
    });

    // Reconnect immediately when page is restored from bfcache
    window.addEventListener('pageshow', (e) => {
      this._isPageHidden = false;
      if (e.persisted || !this._ws || this._ws.readyState !== WebSocket.OPEN) {
        console.log('[Realtime WS] Restoring connection on pageshow');
        this.initWebSocket();
      }
    });

    // Handle tab switching / screen lock
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        this._isPageHidden = false;
        if (!this._ws || (this._ws.readyState !== WebSocket.OPEN && this._ws.readyState !== WebSocket.CONNECTING)) {
          this.initWebSocket();
        }
      } else if (document.visibilityState === 'hidden') {
        this._isPageHidden = true;
      }
    });
  },

  initWebSocket() {
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/realtime`;

    try {
      this._wsConnecting = true;
      const ws = new WebSocket(wsUrl);
      this._ws = ws;

      ws.onopen = () => {
        console.log('[Realtime] WebSocket connected');
        this._wsConnecting = false;
        this._wsReconnectDelay = 1000;
        const badge = document.getElementById('live-indicator-badge');
        if (badge) {
          badge.classList.remove('offline');
          badge.title = 'ওয়েবসকেট লাইভ সিঙ্ক সক্রিয় (WebSocket Connected)';
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong') return;

          if (this._lastDataVersion !== null && this._lastDataVersion !== data.version) {
            console.log(`[Realtime WS] Change event: v${this._lastDataVersion} -> v${data.version}`);
            this._realtimeCallbacks.forEach(cb => {
              try { cb(data); } catch (e) { console.error('[WS Callback error]', e); }
            });
          }
          this._lastDataVersion = data.version;
        } catch (err) {
          console.warn('[Realtime WS] Message parse error:', err);
        }
      };

      ws.onerror = () => {};

      ws.onclose = (event) => {
        this._ws = null;
        this._wsConnecting = false;
        const badge = document.getElementById('live-indicator-badge');
        if (badge) badge.classList.add('offline');

        if (this._isPageHidden) return;

        clearTimeout(this._wsReconnectTimer);
        this._wsReconnectTimer = setTimeout(() => {
          if (!this._isPageHidden) {
            this._wsReconnectDelay = Math.min(this._wsReconnectDelay * 1.5, 8000);
            this.initWebSocket();
          }
        }, this._wsReconnectDelay);
      };

      if (!this._pingInterval) {
        this._pingInterval = setInterval(() => {
          if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send('ping');
          }
        }, 20000);
      }
    } catch (e) {
      this._wsConnecting = false;
      setTimeout(() => this.initWebSocket(), 3000);
    }
  },

  /* ── Donors ── */
  async getDonors() {
    try { return await _api('GET', '/api/donors'); }
    catch (e) { console.error('[DataStore] getDonors:', e.message); return []; }
  },

  async getDonorById(id) {
    try { return await _api('GET', `/api/donors/${encodeURIComponent(id)}`); }
    catch (e) { console.error('[DataStore] getDonorById:', e.message); return null; }
  },

  async addDonor(donor) {
    try {
      const created = await _api('POST', '/api/donors', donor);
      _currentUser = created;
      _authCallbacks.forEach(cb => { try { cb('SIGNED_IN', { user: created }); } catch (_) {} });
      return created;
    } catch (e) {
      console.error('[DataStore] addDonor:', e.message);
      throw e;
    }
  },

  async updateDonor(id, updates) {
    try { await _api('PUT', `/api/donors/${encodeURIComponent(id)}`, updates); }
    catch (e) { console.error('[DataStore] updateDonor:', e.message); }
  },

  async searchDonors({ bloodGroup, district, upazila, area, availability } = {}) {
    try {
      const params = new URLSearchParams();
      if (bloodGroup)   params.set('bloodGroup',   bloodGroup);
      if (district)     params.set('district',     district);
      if (upazila)      params.set('upazila',      upazila);
      if (area)         params.set('area',         area);
      if (availability) params.set('availability', availability);
      const qs = params.toString();
      return await _api('GET', `/api/donors/search${qs ? '?' + qs : ''}`);
    } catch (e) { console.error('[DataStore] searchDonors:', e.message); return []; }
  },

  /* ── Blood Requests ── */
  async getRequests() {
    try { return await _api('GET', '/api/requests'); }
    catch (e) { console.error('[DataStore] getRequests:', e.message); return []; }
  },

  async addRequest(req) {
    try { return await _api('POST', '/api/requests', req); }
    catch (e) { console.error('[DataStore] addRequest:', e.message); throw e; }
  },

  async updateRequest(id, updates) {
    try { await _api('PUT', `/api/requests/${encodeURIComponent(id)}`, updates); }
    catch (e) { console.error('[DataStore] updateRequest:', e.message); }
  },

  /* ── Contact Requests ── */
  async getContactRequests() {
    try { return await _api('GET', '/api/contacts'); }
    catch (e) { console.error('[DataStore] getContactRequests:', e.message); return []; }
  },

  async addContactRequest(req) {
    try { return await _api('POST', '/api/contacts', req); }
    catch (e) { console.error('[DataStore] addContactRequest:', e.message); throw e; }
  },

  async updateContactRequest(id, updates) {
    try { await _api('PUT', `/api/contacts/${encodeURIComponent(id)}`, updates); }
    catch (e) { console.error('[DataStore] updateContactRequest:', e.message); }
  },

  /* ── Authentication ── */
  async checkPhone(phone) {
    if (!phone) return { exists: false };
    try {
      return await _api('GET', `/api/auth/check-phone?phone=${encodeURIComponent(phone.trim())}`);
    } catch (e) {
      console.warn('[DataStore] checkPhone error:', e.message);
      return { exists: false, error: e.message };
    }
  },
  async googleAuth(credential, phone = null) {
    const payload = { credential };
    if (phone) payload.phone = phone;
    const res = await _api('POST', '/api/auth/google', payload);
    const { token, user } = res;
    _setToken(token);
    _currentUser = user;
    _authCallbacks.forEach(cb => { try { cb('SIGNED_IN', { user }); } catch (_) {} });
    return res;
  },

  async signup(phone, pin, turnstileToken) {
    const payload = { phone, pin };
    if (turnstileToken) payload.turnstile_token = turnstileToken;
    const { token, user } = await _api('POST', '/api/auth/signup', payload);
    _setToken(token);
    _currentUser = user;
    _authCallbacks.forEach(cb => { try { cb('SIGNED_IN', { user }); } catch (_) {} });
    return user;
  },

  async login(phone, pin, turnstileToken) {
    const payload = { phone, pin };
    if (turnstileToken) payload.turnstile_token = turnstileToken;
    const { token, user } = await _api('POST', '/api/auth/login', payload);
    _setToken(token);
    _currentUser = user;
    _authCallbacks.forEach(cb => { try { cb('SIGNED_IN', { user }); } catch (_) {} });
    return user;
  },

  async logout() {
    try { await _api('POST', '/api/auth/logout'); } catch (_) {}
    _setToken(null);
    _currentUser = null;
    _authCallbacks.forEach(cb => { try { cb('SIGNED_OUT', null); } catch (_) {} });
    window.location.hash = '#home';
    if (window.App && typeof App.navigate === 'function') {
      App.navigate('home');
      if (typeof App.renderNav === 'function') App.renderNav();
    } else {
      window.location.reload();
    }
  },

  async getCurrentUser() {
    if (!_getToken()) return null;
    try {
      _currentUser = await _api('GET', '/api/auth/me');
      return _currentUser;
    } catch (e) {
      if (e.status === 401) { _setToken(null); _currentUser = null; }
      return null;
    }
  },

  onAuthStateChange(callback) {
    _authCallbacks.push(callback);
  },

  /* ── Notifications (in-memory for session) ── */
  _notifications: [],
  getNotifications() { return this._notifications; },
  addNotification(notif) {
    this._notifications.unshift(notif);
    if (this._notifications.length > 50) this._notifications.length = 50;
  },

  /* ── Helpers ── */
  generateId(prefix) {
    return (prefix || '') + Date.now().toString(36).toUpperCase();
  },
};

/* ── Utils (unchanged) ── */
const Utils = {
  formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleDateString('bn-BD', { day: 'numeric', month: 'long', year: 'numeric' });
  },
  formatTime12(timeStr) {
    if (!timeStr) return '';
    const [h, m] = timeStr.split(':');
    let hours = parseInt(h);
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
    return `${hours}:${m} ${ampm}`;
  },
  monthsAgo(dateStr) {
    if (!dateStr) return null;
    const diff = new Date() - new Date(dateStr);
    const months = Math.floor(diff / (1000 * 60 * 60 * 24 * 30));
    if (months === 0) return 'এই মাসে';
    if (months === 1) return '১ মাস আগে';
    return `${months} মাস আগে`;
  },
  maskPhone(phone) {
    return phone.replace(/(\d{4})\d+(\d{3})/, '$1***$2');
  },
  getStatusBadge(status) {
    const map = {
      pending:      { label: 'যাচাই বাকি', class: 'status-pending', icon: '<i class="fas fa-clock"></i>' },
      under_review: { label: 'পর্যালোচনা চলছে', class: 'status-review', icon: '<i class="fas fa-spinner fa-spin"></i>' },
      verified:     { label: 'যাচাইকৃত', class: 'status-verified', icon: '<i class="fas fa-circle-check"></i>' },
      rejected:     { label: 'প্রত্যাখ্যাত', class: 'status-rejected', icon: '<i class="fas fa-circle-xmark"></i>' },
      completed:    { label: 'সম্পন্ন', class: 'status-completed', icon: '<i class="fas fa-circle-check"></i>' },
      expired:      { label: 'মেয়াদোত্তীর্ণ', class: 'status-expired', icon: '<i class="fas fa-hourglass-end"></i>' },
    };
    return map[status] || map.pending;
  },
  getAvailabilityInfo(av) {
    const map = {
      available:   { label: 'পাওয়া যাচ্ছে', class: 'avail-yes', dot: 'dot-green' },
      soon:        { label: 'শীঘ্রই পাওয়া যাবে', class: 'avail-soon', dot: 'dot-amber' },
      unavailable: { label: 'এখন পাওয়া যাবে না', class: 'avail-no', dot: 'dot-red' },
    };
    return map[av] || map.unavailable;
  },
  getBadgeInfo(badge) {
    const map = {
      registered: { label: '<i class="fas fa-droplet"></i> নিবন্ধিত দাতা', class: 'badge-registered' },
      bronze:     { label: '<i class="fas fa-award" style="color:#cd7f32"></i> ব্রোঞ্জ দাতা', class: 'badge-bronze' },
      silver:     { label: '<i class="fas fa-award" style="color:#c0c0c0"></i> সিলভার দাতা', class: 'badge-silver' },
      gold:       { label: '<i class="fas fa-medal" style="color:#ffd700"></i> গোল্ড দাতা', class: 'badge-gold' },
      lifesaver:  { label: '<i class="fas fa-gem" style="color:#00e5ff"></i> লাইফ সেভার', class: 'badge-lifesaver' },
      verified:   { label: '<i class="fas fa-circle-check" style="color:#00e676"></i> যাচাইকৃত দাতা', class: 'badge-verified' },
    };
    return map[badge] || map.registered;
  },
  getVerificationLabel(level) {
    const labels = [
      'অযাচাইকৃত',
      '<i class="fas fa-mobile"></i> মোবাইল যাচাই',
      '<i class="fas fa-id-card"></i> পরিচয় যাচাই',
      '<i class="fas fa-droplet"></i> রক্তের গ্রুপ যাচাই',
      '<i class="fas fa-star"></i> রিনিউয়েল যাচাইকৃত'
    ];
    return labels[level] || labels[0];
  },
  calcTrustScore(donor) {
    let score = 0;
    if (donor.verificationLevel >= 1) score += 15;
    if (donor.verificationLevel >= 2) score += 20;
    if (donor.verificationLevel >= 3) score += 25;
    if (donor.verificationLevel >= 4) score += 20;
    const donations = Math.min(donor.donationCount, 10);
    score += donations * 2;
    if (!donor.reported) score += 5;
    return Math.min(score, 100);
  },
  toEnglishNum(n) { return String(n); }
};

window.DataStore      = DataStore;
window.Utils          = Utils;
window.BD_LOCATIONS   = BD_LOCATIONS;
window.BLOOD_GROUPS   = BLOOD_GROUPS;
window.DONATION_TYPES = DONATION_TYPES;
