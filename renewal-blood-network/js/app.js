/* ============================================================
   RENEWAL BLOOD NETWORK — SPA Router & App Controller
   ============================================================ */

const App = {
  currentPage: 'home',

  routes: {
    home:       () => App.loadHome(),
    'find-donor': () => App.loadFindDonor(),
    'register': () => App.loadRegister(),
    'emergency': () => App.loadEmergency(),
    'dashboard': () => App.loadDashboard(),
    'map':      () => App.loadMap(),
    'leaderboard': () => App.loadLeaderboard(),
  },

  async init() {
    await DataStore.init();
    this.setupNavbar();
    this.setupRouter();
    this.setupAuth();
    this.setupRealtimeSync();
    await this.updateAuthUI();
    this.navigate(location.hash.slice(1) || 'home');
    this.setupMobileMenu();
    this.setupToastContainer();
    setTimeout(() => this.renderGoogleAuth(), 400);
  },

  async navigate(page) {
    if (!page) page = 'home';

    // If already registered donor, completely block access to registration
    if (page === 'register') {
      const user = await DataStore.getCurrentUser();
      if (user && !user.isNew) {
        Toast.show({
          type: 'info',
          title: 'ইতিমধ্যে নিবন্ধিত রক্তদাতা',
          message: 'আপনি ইতিমধ্যে নিবন্ধিত আছেন। ড্যাশবোর্ড প্রদর্শিত হচ্ছে।',
          duration: 3500
        });
        this.navigate('dashboard');
        return;
      }
    }

    this.currentPage = page;

    // Hide all pages
    if (page === 'admin') {
      window.location.href = 'http://localhost:8081'; // Redirect to standalone Admin Panel
      return;
    }

    // Hide all views
    document.querySelectorAll('.page-view').forEach(v => v.classList.remove('active'));

    const view = document.getElementById('view-' + page);
    if (view) {
      view.classList.add('active');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Update active nav
    document.querySelectorAll('[data-nav]').forEach(a => {
      a.classList.toggle('active', a.dataset.nav === page);
    });

    location.hash = page;

    // Run route handler
    if (this.routes[page]) this.routes[page]();
  },

  setupRouter() {
    // All navigation links
    document.querySelectorAll('[data-page]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const pg = el.dataset.page;
        App.navigate(pg);
        App.closeMobileMenu();
      });
    });

    window.addEventListener('hashchange', () => {
      const pg = location.hash.slice(1);
      if (pg && pg !== App.currentPage) App.navigate(pg);
    });
  },

  setupNavbar() {
    window.addEventListener('scroll', () => {
      const nb = document.getElementById('navbar');
      if (nb) nb.classList.toggle('scrolled', window.scrollY > 30);
    });
  },

  setupMobileMenu() {
    const btn = document.getElementById('hamburger');
    const menu = document.getElementById('mobile-menu');
    if (btn && menu) {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('open');
        document.body.classList.toggle('menu-open', menu.classList.contains('open'));
      });
      menu.addEventListener('click', (e) => {
        if (e.target === menu || e.target.closest('.mobile-drawer-close')) {
          App.closeMobileMenu();
        }
      });
    }
  },

  closeMobileMenu() {
    const menu = document.getElementById('mobile-menu');
    if (menu) {
      menu.classList.remove('open');
      document.body.classList.remove('menu-open');
    }
  },

  setupToastContainer() {
    if (!document.getElementById('toast-container')) {
      const tc = document.createElement('div');
      tc.id = 'toast-container';
      tc.className = 'toast-container';
      document.body.appendChild(tc);
    }
  },

  setupAuth() {
    DataStore.onAuthStateChange(async (event, session) => {
      this.updateAuthUI();
    });
  },

  setupRealtimeSync() {
    DataStore.subscribeToChanges(async (versionData) => {
      // 1. Indicate sync on live badge in navbar
      const badge = document.getElementById('live-indicator-badge') || document.getElementById('navbar-live-sync-badge');
      if (badge) {
        badge.classList.add('syncing');
        const textSpan = badge.querySelector('.live-text');
        if (textSpan) textSpan.textContent = 'SYNC';
        setTimeout(() => {
          badge.classList.remove('syncing');
          if (textSpan) textSpan.textContent = 'LIVE';
        }, 1200);
      }

      // 2. Realtime refresh based on current view & global components
      try {
        // Refresh home stats, blood groups, marquee ticker & leaderboard showcase
        if (this.currentPage === 'home' || !this.currentPage) {
          if (typeof HomeModule !== 'undefined') {
            if (HomeModule.refreshLiveStats) HomeModule.refreshLiveStats(versionData);
            if (HomeModule.renderBloodGroupOverview) HomeModule.renderBloodGroupOverview();
            if (HomeModule.renderEmergencyFeed) HomeModule.renderEmergencyFeed();
            if (HomeModule.renderHomeLeaderboard) HomeModule.renderHomeLeaderboard();
          }
        }

        // Refresh emergency view if active
        if (this.currentPage === 'emergency' && typeof EmergencyModule !== 'undefined') {
          if (typeof EmergencyModule.renderActiveRequests === 'function') {
            EmergencyModule.renderActiveRequests();
          }
        }

        // Refresh find donor search / filter results if active
        if (this.currentPage === 'find' && typeof DonorModule !== 'undefined') {
          if (typeof DonorModule.doSearch === 'function') {
            DonorModule.doSearch();
          }
        }

        // Refresh leaderboard view if active
        if (this.currentPage === 'leaderboard' && typeof LeaderboardModule !== 'undefined') {
          LeaderboardModule.render();
        }

        // Refresh donor dashboard if active
        if (this.currentPage === 'dashboard' && typeof DashboardModule !== 'undefined') {
          DashboardModule.render();
        }

        // Refresh map if active
        if (this.currentPage === 'map' && typeof MapModule !== 'undefined' && MapModule.loadDonorMarkers) {
          MapModule.loadDonorMarkers();
        }
      } catch (err) {
        console.warn('[Realtime Sync Error]', err);
      }
    });
  },

  async updateAuthUI() {
    const user = await DataStore.getCurrentUser();
    const btnLogin = document.getElementById('nav-login-btn');
    const btnLogout = document.getElementById('nav-logout-btn');
    const mobLogin = document.getElementById('mobile-login-btn');
    const mobLogout = document.getElementById('mobile-logout-btn');
    const navRegLi = document.getElementById('nav-register-li');
    const mobRegLink = document.getElementById('mobile-register-link');
    const homeCtaReg = document.getElementById('home-cta-register');
    const homeCtaRegTitle = document.getElementById('home-cta-register-title');
    const homeCtaRegSub = document.getElementById('home-cta-register-sub');
    const homeCtaRegBtn = document.getElementById('home-cta-register-btn');

    const isRegisteredDonor = user && !user.isNew;

    const mobUserCard = document.getElementById('mobile-user-card');
    const mobUserName = document.getElementById('mobile-user-name');
    const mobUserPhone = document.getElementById('mobile-user-phone');
    const mobUserAvatar = document.getElementById('mobile-user-avatar');

    if (user) {
      const displayName = (user.name && user.name !== 'User') ? user.name : (user.oauth_name || (user.email ? user.email.split('@')[0] : (user.phone || 'ইউজার')));
      if (mobUserCard) mobUserCard.style.display = 'flex';
      if (mobUserName) mobUserName.textContent = displayName;
      if (mobUserPhone) mobUserPhone.textContent = user.phone || '';
      if (mobUserAvatar) mobUserAvatar.textContent = (displayName[0] || 'র').toUpperCase();
      if (btnLogin) btnLogin.style.display = 'none';
      if (btnLogout) {
        btnLogout.style.display = 'block';
        btnLogout.innerHTML = `<i class="fas fa-arrow-right-from-bracket"></i> লগআউট (${displayName})`;
      }
      if (mobLogin) mobLogin.style.display = 'none';
      if (mobLogout) {
        mobLogout.style.display = 'block';
        mobLogout.innerHTML = `<i class="fas fa-arrow-right-from-bracket"></i> লগআউট (${displayName})`;
      }
    } else {
      if (mobUserCard) mobUserCard.style.display = 'none';
      if (btnLogin) btnLogin.style.display = 'block';
      if (btnLogout) btnLogout.style.display = 'none';
      if (mobLogin) mobLogin.style.display = 'block';
      if (mobLogout) mobLogout.style.display = 'none';
    }

    // Completely remove registration button & options when logged in as registered donor
    if (isRegisteredDonor) {
      if (navRegLi) navRegLi.style.display = 'none';
      if (mobRegLink) mobRegLink.style.display = 'none';
      if (homeCtaReg) {
        homeCtaReg.dataset.page = 'dashboard';
        homeCtaReg.onclick = (e) => { e.preventDefault(); App.navigate('dashboard'); };
      }
      if (homeCtaRegTitle) homeCtaRegTitle.textContent = 'আমার ড্যাশবোর্ড';
      if (homeCtaRegSub) homeCtaRegSub.textContent = 'আপনার রক্তদাতা প্রোফাইল ও রক্তদানের হিস্ট্রি পরিচালনা করুন';
      if (homeCtaRegBtn) {
        homeCtaRegBtn.dataset.page = 'dashboard';
        homeCtaRegBtn.innerHTML = 'ড্যাশবোর্ড দেখুন <i class="fas fa-arrow-right"></i>';
        homeCtaRegBtn.onclick = (e) => { e.preventDefault(); e.stopPropagation(); App.navigate('dashboard'); };
      }
    } else {
      if (navRegLi) navRegLi.style.display = '';
      if (mobRegLink) mobRegLink.style.display = '';
      if (homeCtaReg) {
        homeCtaReg.dataset.page = 'register';
        homeCtaReg.onclick = (e) => { e.preventDefault(); App.navigate('register'); };
      }
      if (homeCtaRegTitle) homeCtaRegTitle.textContent = 'আমি রক্ত দিতে চাই';
      if (homeCtaRegSub) homeCtaRegSub.textContent = 'রক্তদাতা হিসেবে নিবন্ধন করুন এবং জীবন বাঁচানোর অংশ হোন';
      if (homeCtaRegBtn) {
        homeCtaRegBtn.dataset.page = 'register';
        homeCtaRegBtn.innerHTML = 'নিবন্ধন করুন <i class="fas fa-arrow-right"></i>';
        homeCtaRegBtn.onclick = (e) => { e.preventDefault(); e.stopPropagation(); App.navigate('register'); };
      }
    }
  },

  _authTurnstileWidgetId: null,
  _authTurnstileToken: null,

  renderAuthTurnstile() {
    const container = document.getElementById('auth-turnstile-container');
    if (!container) return;

    const renderFn = () => {
      if (window.turnstile && typeof window.turnstile.render === 'function') {
        if (container.querySelector('iframe')) return;
        try {
          const siteKey = (DataStore.config && DataStore.config.turnstileSiteKey) || '1x00000000000000000000AA';
          container.innerHTML = '';
          this._authTurnstileWidgetId = window.turnstile.render(container, {
            sitekey: siteKey,
            callback: (token) => {
              this._authTurnstileToken = token;
              const errEl = document.getElementById('auth-turnstile-error');
              if (errEl) errEl.style.display = 'none';
            },
            'expired-callback': () => {
              this._authTurnstileToken = null;
            },
            theme: 'light'
          });
        } catch (e) {
          console.warn('[Turnstile Auth] render error:', e.message);
        }
      }
    };

    if (window.turnstile) {
      renderFn();
    } else {
      let attempts = 0;
      const interval = setInterval(() => {
        attempts++;
        if (window.turnstile || attempts > 15) {
          clearInterval(interval);
          if (window.turnstile) renderFn();
        }
      }, 200);
    }
  },

  resetAuthTurnstile() {
    this._authTurnstileToken = null;
    if (window.turnstile && typeof window.turnstile.reset === 'function') {
      try {
        if (this._authTurnstileWidgetId !== null) {
          window.turnstile.reset(this._authTurnstileWidgetId);
        } else {
          window.turnstile.reset('#auth-turnstile-container');
        }
      } catch (_) {}
    }
  },

  renderGoogleAuth() {
    const config = DataStore.config;
    if (!config || config.googleLoginEnabled === false) return;

    const clientId = config.googleClientId;
    const loginContainer = document.getElementById('google-login-container');
    const signupContainer = document.getElementById('google-signup-container');

    // Default stylish Google button HTML for instant UI & fallback
    const createPlaceholderHtml = (text = 'Google দিয়ে চালিয়ে যান') => `
      <button type="button" class="btn btn-outline" onclick="App.onGooglePlaceholderClick()" style="display:inline-flex;align-items:center;justify-content:center;gap:0.6rem;background:#ffffff;border:1px solid #dadce0;border-radius:24px;padding:0.5rem 1.1rem;font-size:0.88rem;font-weight:500;color:#3c4043;cursor:pointer;width:100%;max-width:280px;box-shadow:0 1px 2px rgba(0,0,0,0.06);transition:all 0.2s ease;">
        <svg style="width:18px;height:18px;" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
        <span style="font-family:var(--font-bn);">${text}</span>
      </button>
    `;

    if (!clientId) {
      if (loginContainer) loginContainer.innerHTML = createPlaceholderHtml('Google দিয়ে লগইন');
      if (signupContainer) signupContainer.innerHTML = createPlaceholderHtml('Google দিয়ে নিবন্ধন');
      return;
    }

    if (!window.google || !window.google.accounts || !window.google.accounts.id) {
      // Library still loading
      if (loginContainer && !loginContainer.hasChildNodes()) loginContainer.innerHTML = createPlaceholderHtml('Google দিয়ে লগইন');
      if (signupContainer && !signupContainer.hasChildNodes()) signupContainer.innerHTML = createPlaceholderHtml('Google দিয়ে নিবন্ধন');
      setTimeout(() => this.renderGoogleAuth(), 400);
      return;
    }

    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (resp) => this.handleGoogleCredentialResponse(resp),
        auto_select: false,
        cancel_on_tap_outside: true
      });

      if (loginContainer) {
        loginContainer.innerHTML = '';
        window.google.accounts.id.renderButton(loginContainer, {
          theme: 'outline',
          size: 'large',
          text: 'continue_with',
          shape: 'pill',
          width: 280,
          logo_alignment: 'left'
        });
      }

      if (signupContainer) {
        signupContainer.innerHTML = '';
        window.google.accounts.id.renderButton(signupContainer, {
          theme: 'outline',
          size: 'medium',
          text: 'signup_with',
          shape: 'pill',
          logo_alignment: 'left'
        });
      }
    } catch (e) {
      console.warn('[Google Auth] render error:', e.message);
      if (loginContainer) loginContainer.innerHTML = createPlaceholderHtml('Google দিয়ে লগইন');
      if (signupContainer) signupContainer.innerHTML = createPlaceholderHtml('Google দিয়ে নিবন্ধন');
    }
  },

  onGooglePlaceholderClick() {
    const clientId = DataStore.config && DataStore.config.googleClientId;
    if (!clientId) {
      Toast.show({
        type: 'info',
        title: 'গুগল ক্লায়েন্ট আইডি প্রয়োজন',
        message: 'গুগল সাইন-ইন চালু করতে .env ফাইলে GOOGLE_CLIENT_ID কী (Key) সেট করুন।',
        duration: 5000
      });
    } else {
      Toast.show({
        type: 'info',
        title: 'লোড হচ্ছে...',
        message: 'Google Identity Services লোড হচ্ছে, এক মুহূর্ত অপেক্ষা করুন...',
        duration: 2500
      });
      this.renderGoogleAuth();
    }
  },

  async handleGoogleCredentialResponse(response) {
    if (!response || !response.credential) {
      Toast.show({ type: 'error', title: 'গুগল যাচাই ব্যর্থ', message: 'কোনো ভেরিফিকেশন টোকেন পাওয়া যায়নি।' });
      return;
    }

    try {
      Toast.show({ type: 'info', title: 'যাচাই করা হচ্ছে...', message: 'Google ক্রেডেনশিয়াল নিশ্চিত করা হচ্ছে...', duration: 2500 });
      const res = await DataStore.googleAuth(response.credential);
      Modal.close('auth-modal');
      await this.updateAuthUI();

      const user = res.user;

      if (res.isNew || !res.hasDonorProfile) {
        Toast.show({
          type: 'success',
          title: 'Google সাইন-ইন সফল!',
          message: `স্বাগতম ${user?.name || ''}! অনুগ্রহ করে আপনার রক্তদাতা তথ্য সম্পন্ন করুন।`,
          duration: 4000
        });

        // Pre-fill name on registration form
        const nameInput = document.getElementById('r-name');
        if (nameInput && user?.name) {
          nameInput.value = user.name;
        }

        // Show Google verified badge on registration step 1
        const gBadge = document.getElementById('google-verified-badge');
        const gContainer = document.getElementById('google-signup-container');
        if (gBadge) {
          gBadge.style.display = 'inline-flex';
          gBadge.innerHTML = `<i class="fa-brands fa-google"></i> ভেরিফাইড: ${user?.email || user?.name || ''}`;
        }
        if (gContainer) {
          gContainer.style.display = 'none';
        }

        if (window.location.hash !== '#register') {
          App.navigate('register');
        }
      } else {
        Toast.show({
          type: 'success',
          title: 'লগইন সফল!',
          message: `স্বাগতম ${user?.name || ''}! ড্যাশবোর্ডে প্রবেশ করা হচ্ছে...`,
          duration: 3000
        });
        App.navigate('dashboard');
      }
    } catch (err) {
      Toast.show({ type: 'error', title: 'গুগল সাইন-ইন ত্রুটি', message: err.message || 'যাচাইকরণ ব্যর্থ হয়েছে।' });
    }
  },

  async handleAuthSubmit() {
    const phone = document.getElementById('auth-phone').value.trim();
    const pin = document.getElementById('auth-pin').value.trim();
    const btn = document.getElementById('auth-submit-btn');
    
    if (!/^01[3-9]\d{8}$/.test(phone)) {
      alert('সঠিক ১১-ডিজিটের মোবাইল নম্বর দিন (যেমন: 017XXXXXXXX)');
      return;
    }
    if (!/^\d{4}$/.test(pin)) {
      alert('৪-ডিজিটের গোপন পিন দিন');
      return;
    }

    // Verify Turnstile for Login
    const turnstileToken = this._authTurnstileToken ||
      document.getElementById('auth-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

    const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
    if (isTurnstileRequired && window.turnstile && !turnstileToken) {
      const errEl = document.getElementById('auth-turnstile-error');
      if (errEl) errEl.style.display = 'block';
      Toast.show({
        type: 'warning',
        title: 'ক্যাপচা যাচাই প্রয়োজন',
        message: 'অনুগ্রহ করে আমি রোবট নই (Cloudflare Turnstile) যাচাইটি সম্পন্ন করুন।'
      });
      return;
    }

    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> অপেক্ষা করুন...';
    
    try {
      try {
        await DataStore.login(phone, pin, turnstileToken);
      } catch (err) {
        this.resetAuthTurnstile();
        if (err.message.includes('Invalid login credentials')) {
          alert('ভুল নম্বর বা পিন দিয়েছেন। আপনার অ্যাকাউন্ট না থাকলে নতুন করে নিবন্ধন করুন।');
        } else {
          alert('ত্রুটি: ' + err.message);
        }
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-arrow-right-to-bracket"></i> লগইন';
        return;
      }
      
      Modal.close('auth-modal');
      const phoneInput = document.getElementById('auth-phone');
      const pinInput = document.getElementById('auth-pin');
      if (phoneInput) phoneInput.value = '';
      if (pinInput) pinInput.value = '';

      await this.updateAuthUI();
      const user = await DataStore.getCurrentUser();

      Toast.show({
        type: 'success',
        title: 'লগইন সফল!',
        message: `স্বাগতম ${user?.name || ''}! ড্যাশবোর্ডে প্রবেশ করা হচ্ছে...`,
        duration: 3000
      });

      if (user && user.isNew) {
        // Logged in but not a donor yet.
        App.navigate('register');
      } else {
        App.navigate('dashboard');
      }
      
    } catch (err) {
      alert('ত্রুটি হয়েছে: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-arrow-right-to-bracket"></i> এগিয়ে যান';
    }
  },

  // ── Page Loaders ──
  loadHome()       { HomeModule.render(); },
  loadFindDonor()  { DonorModule.renderSearch(); },
  loadRegister()   { 
    DonorModule.renderRegistration(); 
    setTimeout(() => this.renderGoogleAuth(), 120);
  },
  loadEmergency()  { EmergencyModule.render(); },
  loadDashboard()  { DashboardModule.render(); },
  loadMap()        { MapModule.render(); },
  loadLeaderboard(){ LeaderboardModule.render(); },
};

// ── Toast Notification System ──
const Toast = {
  show({ title, message, type = 'info', duration = 4000 }) {
    const tc = document.getElementById('toast-container');
    if (!tc) return;

    const icons = {
      success: '<i class="fas fa-circle-check" style="color:var(--verified-green)"></i>',
      error: '<i class="fas fa-circle-xmark" style="color:var(--blood-red)"></i>',
      info: '<i class="fas fa-circle-info" style="color:var(--status-review)"></i>',
      warning: '<i class="fas fa-triangle-exclamation" style="color:var(--pending-amber)"></i>',
      emergency: '<i class="fas fa-bolt" style="color:#FF1744"></i>'
    };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || icons.info}</span>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${message ? `<div class="toast-msg">${message}</div>` : ''}
      </div>
      <button onclick="this.closest('.toast').remove()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.85rem;padding:0 0.25rem;"><i class="fas fa-xmark"></i></button>
    `;
    tc.appendChild(toast);
    if (duration > 0) {
      setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
      }, duration);
    }
    return toast;
  }
};

// ── Modal System ──
const Modal = {
  open(id) {
    const m = document.getElementById(id);
    if (m) {
      m.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      if (id === 'auth-modal' && window.App) {
        if (typeof App.renderAuthTurnstile === 'function') setTimeout(() => App.renderAuthTurnstile(), 60);
        if (typeof App.renderGoogleAuth === 'function') setTimeout(() => App.renderGoogleAuth(), 80);
      }
    }
  },
  close(id) {
    const m = document.getElementById(id);
    if (m) {
      m.classList.add('hidden');
      document.body.style.overflow = '';
      if (id === 'auth-modal' && window.App && typeof App.resetAuthTurnstile === 'function') {
        App.resetAuthTurnstile();
      }
    }
  },
  closeAll() {
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => {
      m.classList.add('hidden');
    });
    document.body.style.overflow = '';
  }
};

// Close modal on overlay click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) Modal.closeAll();
});

// ── Counter Animation ──
function animateCounter(el, target, duration = 1500) {
  const start = 0;
  const step = target / (duration / 16);
  let current = start;
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = Math.floor(current).toLocaleString('en');
    if (current >= target) clearInterval(timer);
  }, 16);
}

// ── Intersection Observer for counters ──
const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const el = entry.target;
      const target = parseInt(el.dataset.target);
      if (!isNaN(target) && !el.dataset.animated) {
        el.dataset.animated = '1';
        animateCounter(el, target);
      }
    }
  });
}, { threshold: 0.5 });

window.App    = App;
window.Toast  = Toast;
window.Modal  = Modal;
window.counterObserver = counterObserver;
