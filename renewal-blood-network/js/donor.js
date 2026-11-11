/* ============================================================
   RENEWAL BLOOD NETWORK — Donor Module
   ============================================================ */

const DonorModule = {

  // ── SEARCH ──
  async renderSearch() {
    this.populateSearchFilters();
    await this.doSearch();
  },

  populateSearchFilters() {
    // Blood group dropdown
    const bgSel = document.getElementById('s-blood-group');
    if (bgSel && bgSel.options.length <= 1) {
      BLOOD_GROUPS.forEach(g => {
        const o = document.createElement('option');
        o.value = g; o.textContent = g;
        bgSel.appendChild(o);
      });
    }
    // District dropdown
    const distSel = document.getElementById('s-district');
    if (distSel && distSel.options.length <= 1) {
      Object.keys(BD_LOCATIONS).forEach(d => {
        const o = document.createElement('option');
        o.value = d; o.textContent = d;
        distSel.appendChild(o);
      });
    }
    // Listen for district change
    if (distSel) {
      distSel.onchange = () => {
        const upSel = document.getElementById('s-upazila');
        if (!upSel) return;
        const dist = distSel.value;
        upSel.innerHTML = '<option value="">সব উপজেলা</option>';
        if (dist && BD_LOCATIONS[dist]) {
          BD_LOCATIONS[dist].forEach(u => {
            const o = document.createElement('option');
            o.value = u; o.textContent = u;
            upSel.appendChild(o);
          });
        }
      };
    }
  },

  async doSearch() {
    const bg   = document.getElementById('s-blood-group')?.value || '';
    const dist = document.getElementById('s-district')?.value || '';
    const up   = document.getElementById('s-upazila')?.value || '';
    const avl  = document.getElementById('s-availability')?.value || '';

    const container = document.getElementById('donor-results');
    const countEl   = document.getElementById('result-count');
    if (!container) return;

    // Show loading state
    container.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon"><i class="fas fa-spinner fa-spin"></i></div><p>দাতা খোঁজা হচ্ছে...</p></div>';

    const donors = await DataStore.searchDonors({
      bloodGroup: bg, district: dist, upazila: up, availability: avl
    });

    if (countEl) countEl.textContent = `${donors.length} জন দাতা পাওয়া গেছে`;

    if (donors.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <div class="empty-icon"><i class="fas fa-droplet"></i></div>
          <p>এই এলাকায় কোনো দাতা পাওয়া যায়নি।<br>অনুগ্রহ করে অন্য ফিল্টার ব্যবহার করুন।</p>
        </div>`;
      return;
    }

    container.innerHTML = donors.map(d => this.renderDonorCard(d)).join('');
  },

  renderDonorCard(d) {
    const avail = Utils.getAvailabilityInfo(d.availability);
    const badge = Utils.getBadgeInfo(d.badge);
    const initials = d.name.charAt(0);
    const lastDon = Utils.monthsAgo(d.lastDonation);
    const vLevel = d.verificationLevel;

    const verifyChips = [
      { label: '<i class="fas fa-mobile"></i> মোবাইল', done: vLevel >= 1 },
      { label: '<i class="fas fa-id-card"></i> পরিচয়', done: vLevel >= 2 },
      { label: '<i class="fas fa-droplet"></i> রক্তের গ্রুপ', done: vLevel >= 3 },
      { label: '<i class="fas fa-star"></i> রিনিউয়েল', done: vLevel >= 4 },
    ].filter(c => c.done).map(c => `<span class="verify-chip done">${c.label} <i class="fas fa-check"></i></span>`).join('');

    return `
    <div class="donor-card anim-fadeInUp">
      <div class="donor-card-header">
        <div style="display:flex;align-items:center;gap:0.75rem;flex:1;min-width:0">
          <div class="donor-avatar">${initials}</div>
          <div style="min-width:0">
            <div class="donor-name">${d.name}</div>
            <div class="donor-location"><i class="fas fa-location-dot"></i> ${d.area}, ${d.upazila}, ${d.district}</div>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.4rem;flex-shrink:0">
          <span class="bg-badge large">${d.bloodGroup}</span>
        </div>
      </div>

      <div style="display:flex;flex-wrap:wrap;gap:0.35rem;margin-bottom:0.75rem">
        ${verifyChips}
        <span class="donor-badge ${badge.class}">${badge.label}</span>
      </div>

      <div class="donor-card-meta">
        <div class="donor-meta-item">
          <span class="donor-meta-label">অবস্থা</span>
          <span class="avail-dot ${avail.dot} ${avail.class}">${avail.label}</span>
        </div>
        <div class="donor-meta-item">
          <span class="donor-meta-label">শেষ রক্তদান</span>
          <span class="donor-meta-value">${lastDon || 'প্রথমবার'}</span>
        </div>
        <div class="donor-meta-item">
          <span class="donor-meta-label">রক্তদানের সংখ্যা</span>
          <span class="donor-meta-value">${d.donationCount} বার</span>
        </div>
        <div class="donor-meta-item">
          <span class="donor-meta-label">Trust Score</span>
          <div style="display:flex;align-items:center;gap:0.4rem">
            <div class="trust-bar-track"><div class="trust-bar-fill" style="width:${d.trustScore}%"></div></div>
            <span class="trust-score-num"><i class="fas fa-star" style="color:#FFD700;font-size:0.7em"></i> ${d.trustScore}</span>
          </div>
        </div>
      </div>

      <div class="donor-card-actions">
        <button class="btn btn-primary btn-sm"
          onclick="DonorModule.openContactModal('${d.id}')">
          <i class="fas fa-paper-plane"></i> যোগাযোগের অনুরোধ
        </button>
        ${d.emergencyCall ? `<button class="btn btn-ghost btn-icon btn-sm" title="সরাসরি ফোন" onclick="DonorModule.openDirectCallModal('${d.id}')"><i class="fas fa-phone"></i></button>` : ''}
      </div>
    </div>`;
  },

  _contactTurnstileWidgetId: null,
  _contactTurnstileToken: null,

  renderContactTurnstile() {
    const container = document.getElementById('contact-turnstile-container');
    if (!container) return;

    const renderFn = () => {
      if (window.turnstile && typeof window.turnstile.render === 'function') {
        if (container.querySelector('iframe')) return;
        try {
          const siteKey = (DataStore.config && DataStore.config.turnstileSiteKey) || '1x00000000000000000000AA';
          container.innerHTML = '';
          this._contactTurnstileWidgetId = window.turnstile.render(container, {
            sitekey: siteKey,
            callback: (token) => {
              this._contactTurnstileToken = token;
              const errEl = document.getElementById('contact-turnstile-error');
              if (errEl) errEl.style.display = 'none';
            },
            'expired-callback': () => {
              this._contactTurnstileToken = null;
            },
            theme: 'light'
          });
        } catch (e) {
          console.warn('[Contact Turnstile] render error:', e.message);
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

  resetContactTurnstile() {
    this._contactTurnstileToken = null;
    if (window.turnstile && typeof window.turnstile.reset === 'function') {
      try {
        if (this._contactTurnstileWidgetId !== null) {
          window.turnstile.reset(this._contactTurnstileWidgetId);
        } else {
          window.turnstile.reset('#contact-turnstile-container');
        }
      } catch (_) {}
    }
  },

  async openContactModal(donorId) {
    const donor = await DataStore.getDonorById(donorId);
    if (!donor) return;

    document.getElementById('contact-donor-name').textContent = donor.name;
    document.getElementById('contact-donor-blood').textContent = donor.bloodGroup;
    document.getElementById('contact-donor-id').value = donorId;

    Modal.open('contact-modal');
    setTimeout(() => this.renderContactTurnstile(), 60);
  },

  async openDirectCallModal(donorId) {
    const donor = await DataStore.getDonorById(donorId);
    if (!donor) return;
    const phone = donor.phone;
    if (phone && !phone.includes('*')) {
      Toast.show({
        type: 'info',
        title: `${donor.name} — সরাসরি যোগাযোগ`,
        message: `মোবাইল নম্বর: <a href="tel:${phone}" style="color:var(--blood-red);font-weight:700;text-decoration:underline">${phone}</a>`,
        duration: 9000
      });
    } else {
      Toast.show({
        type: 'info',
        title: `${donor.name} — সুরক্ষিত যোগাযোগ`,
        message: `দাতার সুরক্ষার্থে নম্বরটি সুরক্ষিত (${phone || 'গোপন'}) রাখা হয়েছে। অনুগ্রহ করে যোগাযোগের অনুরোধ পাঠান।`,
        duration: 6000
      });
      this.openContactModal(donorId);
    }
  },

  async openContactForRequest(requestId) {
    try {
      const requests = await DataStore.getRequests();
      const req = requests.find(r => r.id === requestId);
      if (!req) {
        Toast.show({ type: 'error', title: 'ত্রুটি', message: 'অনুরোধটি খুঁজে পাওয়া যায়নি।' });
        return;
      }

      const currentUser = await DataStore.getCurrentUser();
      if (!currentUser) {
        Toast.show({
          type: 'info',
          title: 'লগইন প্রয়োজন',
          message: 'রক্ত দিতে আগ্রহী হলে অনুগ্রহ করে লগইন বা নিবন্ধন করুন।'
        });
        Modal.open('auth-modal');
        return;
      }

      const contactNum = req.contact || 'জরুরি ডেস্ক';
      Toast.show({
        type: 'emergency',
        title: 'জরুরি রক্তদানের আগ্রহ',
        message: `রোগী: ${req.patientName} (${req.bloodGroup}) • হাসপাতাল: ${req.hospital} • যোগাযোগের নম্বর: <a href="tel:${contactNum}" style="color:#fff;font-weight:bold;text-decoration:underline">${contactNum}</a>`,
        duration: 10000
      });
    } catch (err) {
      console.error('[DonorModule.openContactForRequest]', err);
    }
  },

  async submitContactRequest() {
    let authUser = await DataStore.getCurrentUser();
    if (!authUser) {
      Modal.close('contact-modal');
      Toast.show({ type: 'error', title: 'লগইন করুন', message: 'যোগাযোগের অনুরোধ পাঠাতে আপনাকে লগইন করতে হবে।' });
      Modal.open('auth-modal');
      return;
    }

    const form = document.getElementById('contact-request-form');
    const donorId = document.getElementById('contact-donor-id').value;
    const patient = document.getElementById('cr-patient').value.trim();
    const bloodGroup = document.getElementById('cr-blood').value;
    const hospital = document.getElementById('cr-hospital').value.trim();
    const units = document.getElementById('cr-units').value;
    const phone = document.getElementById('cr-phone').value.trim();

    if (!patient || !bloodGroup || !hospital || !phone) {
      Toast.show({ type: 'error', title: 'ত্রুটি', message: 'সব তথ্য পূরণ করুন।' });
      return;
    }

    // Verify Cloudflare Turnstile token for Contact Request
    const turnstileToken = this._contactTurnstileToken ||
      document.getElementById('contact-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

    const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
    if (!authUser && isTurnstileRequired && window.turnstile && !turnstileToken) {
      const errEl = document.getElementById('contact-turnstile-error');
      if (errEl) errEl.style.display = 'block';
      Toast.show({
        type: 'warning',
        title: 'ক্যাপচা যাচাই প্রয়োজন',
        message: 'অনুগ্রহ করে আমি রোবট নই (Cloudflare Turnstile) যাচাইটি সম্পন্ন করুন।'
      });
      return;
    }

    const req = {
      id: DataStore.generateId('CR'),
      userId: authUser.id,
      donorId, patient, bloodGroup, hospital, units, phone,
      status: 'pending',
      submittedAt: new Date().toISOString(),
    };

    await DataStore.addContactRequest(req);
    Modal.close('contact-modal');

    Toast.show({
      type: 'success',
      title: 'অনুরোধ পাঠানো হয়েছে!',
      message: 'Renewal Foundation শীঘ্রই আপনার সাথে যোগাযোগ করবে।',
      duration: 5000
    });
    form.reset();
  },

  // ── REGISTRATION ──
  currentStep: 1,

  async renderRegistration() {
    this.currentStep = 1;
    this.populateRegisterSelects();
    this.setupPhoneCheck();

    // Check if user is already a registered donor
    const user = await DataStore.getCurrentUser();
    if (user && !user.isNew) {
      Toast.show({
        type: 'info',
        title: 'ইতিমধ্যে নিবন্ধিত রক্তদাতা',
        message: `স্বাগতম ${user.name}! আপনি ইতিমধ্যে নিবন্ধিত আছেন। ড্যাশবোর্ডে প্রবেশ করা হচ্ছে...`,
        duration: 3500
      });
      App.navigate('dashboard');
      return;
    }

    // Ensure phone input is clean, always enabled, and editable
    const phoneInput = document.getElementById('r-phone');
    if (phoneInput) {
      phoneInput.readOnly = false;
      phoneInput.disabled = false;
      phoneInput.style.backgroundColor = '';
      phoneInput.style.cursor = 'text';
      if (user && user.phone) {
        phoneInput.value = user.phone;
      }
    }

    // Pre-fill user details if logged in (e.g. Google Sign-In)
    if (user) {
      const nameInput = document.getElementById('r-name');
      const validUserName = (user.name && user.name !== 'User') ? user.name : (user.oauth_name || (user.email ? user.email.split('@')[0] : ''));
      if (nameInput && validUserName && (!nameInput.value || nameInput.value === 'User')) {
        nameInput.value = validUserName;
      }
      const userEmail = user.email || user.oauth_email;
      if (userEmail) {
        const gBadge = document.getElementById('google-verified-badge');
        const gContainer = document.getElementById('google-signup-container');
        if (gBadge) {
          gBadge.style.display = 'inline-flex';
          gBadge.innerHTML = `<i class="fa-brands fa-google"></i> ভেরিফাইড: ${userEmail}`;
        }
        if (gContainer) {
          gContainer.style.display = 'none';
        }
      }
    }

    this.updateWizardStep(1);
  },

  setupPhoneCheck() {
    const phoneInput = document.getElementById('r-phone');
    if (!phoneInput || phoneInput.dataset.checkBound) return;
    phoneInput.dataset.checkBound = 'true';

    let timeout = null;
    const checkFn = async () => {
      const val = phoneInput.value.trim();
      if (/^01[3-9]\d{8}$/.test(val)) {
        const currentUser = await DataStore.getCurrentUser();
        if (currentUser && currentUser.phone === val && !currentUser.isNew) {
          return;
        }
        const res = await DataStore.checkPhone(val);
        if (res && res.exists) {
          DonorModule.showPhoneDuplicateError(val, res.name);
        } else {
          DonorModule.clearPhoneDuplicateError();
        }
      } else {
        DonorModule.clearPhoneDuplicateError();
      }
    };

    phoneInput.addEventListener('input', () => {
      clearTimeout(timeout);
      timeout = setTimeout(checkFn, 350);
    });

    phoneInput.addEventListener('blur', checkFn);
  },

  showPhoneDuplicateError(phone, donorName) {
    const feedback = document.getElementById('r-phone-feedback');
    const phoneInput = document.getElementById('r-phone');
    if (phoneInput) {
      phoneInput.style.borderColor = 'var(--blood-red)';
      phoneInput.style.backgroundColor = '#FFF5F5';
    }
    if (feedback) {
      feedback.style.display = 'block';
      const nameTxt = donorName ? ` (রক্তদাতা: <strong>${donorName}</strong>)` : '';
      feedback.innerHTML = `
        <div style="background:#FFF1F2;border:1px solid #FECDD3;color:#BE123C;padding:0.6rem 0.85rem;border-radius:8px;margin-top:0.4rem;display:flex;align-items:center;justify-content:space-between;gap:0.6rem;box-shadow:0 1px 3px rgba(0,0,0,0.05);animation:fadeIn 0.2s ease;">
          <div style="font-size:0.85rem;line-height:1.4">
            <strong style="display:flex;align-items:center;gap:0.35rem;color:#E11D48"><i class="fas fa-triangle-exclamation"></i> নম্বরটি ইতিমধ্যে নিবন্ধিত!</strong>
            <div style="font-size:0.8rem;color:#9F1239;margin-top:0.15rem;">এই নম্বর দিয়ে ইতিমধ্যে একজন অ্যাকাউন্ট খুলেছেন${nameTxt}। নতুন অ্যাকাউন্ট না খুলে লগইন করুন।</div>
          </div>
          <button type="button" class="btn btn-sm btn-primary" onclick="Modal.open('auth-modal'); const ap = document.getElementById('auth-phone'); if(ap) ap.value='${phone}';" style="padding:0.35rem 0.75rem;font-size:0.8rem;flex-shrink:0;">
            <i class="fas fa-arrow-right-to-bracket"></i> লগইন
          </button>
        </div>`;
    }
  },

  clearPhoneDuplicateError() {
    const feedback = document.getElementById('r-phone-feedback');
    const phoneInput = document.getElementById('r-phone');
    if (phoneInput) {
      phoneInput.style.borderColor = '';
      phoneInput.style.backgroundColor = '';
    }
    if (feedback) {
      feedback.style.display = 'none';
      feedback.innerHTML = '';
    }
  },

  populateRegisterSelects() {
    // Blood group
    const bgSel = document.getElementById('r-blood-group');
    if (bgSel && bgSel.options.length <= 1) {
      BLOOD_GROUPS.forEach(g => {
        const o = document.createElement('option');
        o.value = g; o.textContent = g;
        bgSel.appendChild(o);
      });
    }
    // District
    const distSel = document.getElementById('r-district');
    if (distSel && distSel.options.length <= 1) {
      Object.keys(BD_LOCATIONS).forEach(d => {
        const o = document.createElement('option');
        o.value = d; o.textContent = d;
        distSel.appendChild(o);
      });
    }
    if (distSel) {
      distSel.onchange = () => {
        const upSel = document.getElementById('r-upazila');
        if (!upSel) return;
        upSel.innerHTML = '<option value="">উপজেলা/থানা বেছে নিন</option>';
        const dist = distSel.value;
        if (dist && BD_LOCATIONS[dist]) {
          BD_LOCATIONS[dist].forEach(u => {
            const o = document.createElement('option');
            o.value = u; o.textContent = u;
            upSel.appendChild(o);
          });
        }
      };
    }
    // Donation types
    const dtSel = document.getElementById('r-donation-types');
    if (dtSel && dtSel.children.length === 0) {
      DONATION_TYPES.forEach(t => {
        const label = document.createElement('label');
        label.className = 'check-item';
        label.innerHTML = `<input type="checkbox" value="${t}"><label>${t}</label>`;
        dtSel.appendChild(label);
      });
    }
  },

  updateWizardStep(step) {
    this.currentStep = step;
    document.querySelectorAll('#register-form-card .wizard-step').forEach((el, i) => {
      const s = i + 1;
      el.classList.toggle('active', s === step);
      el.classList.toggle('done', s < step);
    });
    document.querySelectorAll('#register-form-card .wizard-pane').forEach((pane, i) => {
      pane.classList.toggle('active', i + 1 === step);
    });
    if (step === 1) {
      this.renderTurnstile();
    }
  },

  _turnstileWidgetId: null,

  renderTurnstile() {
    const container = document.getElementById('cf-turnstile-container');
    if (!container) return;

    const renderFn = () => {
      if (window.turnstile && typeof window.turnstile.render === 'function') {
        if (container.querySelector('iframe')) return;
        try {
          const siteKey = (DataStore.config && DataStore.config.turnstileSiteKey) || '1x00000000000000000000AA';
          container.innerHTML = '';
          this._turnstileWidgetId = window.turnstile.render(container, {
            sitekey: siteKey,
            callback: function(token) {
              window._turnstileToken = token;
              const errEl = document.getElementById('turnstile-error');
              if (errEl) errEl.style.display = 'none';
            },
            'expired-callback': function() {
              window._turnstileToken = null;
            },
            'error-callback': function(code) {
              console.warn('[Turnstile] Challenge error code:', code);
            },
            theme: 'light'
          });
        } catch (e) {
          console.warn('[Turnstile] render error:', e.message);
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

  resetTurnstile() {
    window._turnstileToken = null;
    if (window.turnstile && typeof window.turnstile.reset === 'function') {
      try {
        if (this._turnstileWidgetId !== null) {
          window.turnstile.reset(this._turnstileWidgetId);
        } else {
          window.turnstile.reset('#cf-turnstile-container');
        }
      } catch (_) {}
    }
  },

  async nextStep() {
    const valid = await this.validateStep(this.currentStep);
    if (!valid) return;
    this.updateWizardStep(this.currentStep + 1);
  },

  prevStep() {
    if (this.currentStep > 1) this.updateWizardStep(this.currentStep - 1);
  },

  async validateStep(step) {
    if (step === 1) {
      const name = document.getElementById('r-name')?.value.trim();
      const phone = document.getElementById('r-phone')?.value.trim();
      const district = document.getElementById('r-district')?.value;
      const age = document.getElementById('r-age')?.value;
      if (!name || !phone || !district || !age) {
        Toast.show({ type: 'error', title: 'তথ্য অসম্পূর্ণ', message: 'অনুগ্রহ করে সব প্রয়োজনীয় তথ্য পূরণ করুন।' });
        return false;
      }
      if (!/^01[3-9]\d{8}$/.test(phone)) {
        Toast.show({ type: 'error', title: 'ভুল নম্বর', message: 'সঠিক বাংলাদেশী মোবাইল নম্বর দিন (যেমন: 017XXXXXXXX)।' });
        return false;
      }

      // Check duplicate phone
      const currentUser = await DataStore.getCurrentUser();
      if (!currentUser || currentUser.phone !== phone) {
        const check = await DataStore.checkPhone(phone);
        if (check && check.exists) {
          DonorModule.showPhoneDuplicateError(phone, check.name);
          Toast.show({
            type: 'error',
            title: 'নম্বরটি ইতিমধ্যে ব্যবহৃত',
            message: 'এই মোবাইল নম্বরটি দিয়ে ইতিমধ্যে একটি অ্যাকাউন্ট নিবন্ধিত আছে। অনুগ্রহ করে লগইন করুন।',
            duration: 6000
          });
          return false;
        } else {
          DonorModule.clearPhoneDuplicateError();
        }
      }

      // Check Cloudflare Turnstile token on Step 1 (only required for unauthenticated users)
      const currentLoggedInUser = await DataStore.getCurrentUser();
      const turnstileToken = window._turnstileToken ||
        document.querySelector('[name="cf-turnstile-response"]')?.value ||
        document.getElementById('cf-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

      const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
      if (!currentLoggedInUser && isTurnstileRequired && window.turnstile && !turnstileToken) {
        const errEl = document.getElementById('turnstile-error');
        if (errEl) errEl.style.display = 'block';
        Toast.show({
          type: 'warning',
          title: 'ক্যাপচা যাচাই আবশ্যক',
          message: 'অনুগ্রহ করে রোবট নন (Cloudflare Turnstile) ক্যাপচা যাচাই সম্পন্ন করুন।'
        });
        return false;
      }
    }
    if (step === 2) {
      const bg = document.getElementById('r-blood-group')?.value;
      if (!bg) {
        Toast.show({ type: 'error', title: 'রক্তের গ্রুপ নির্বাচন করুন' });
        return false;
      }
    }
    return true;
  },

  async goToStep3() {
    if (!(await this.validateStep(1)) || !(await this.validateStep(2))) return;
    
    // Check if already logged in
    const user = await DataStore.getCurrentUser();
    if (user && !user.isNew) {
      Toast.show({ type: 'info', title: 'ইতিমধ্যেই নিবন্ধিত', message: 'আপনি ইতিমধ্যেই দাতা হিসেবে নিবন্ধিত আছেন।' });
      App.navigate('dashboard');
      return;
    }
    if (user && user.isNew) {
      // Logged in but not a donor yet. Skip PIN step.
      this.submitRegistration();
      return;
    }

    this.updateWizardStep(3);
  },

  async submitRegistration() {
    let authUser = await DataStore.getCurrentUser();
    const phone = document.getElementById('r-phone')?.value.trim();

    // Verify Cloudflare Turnstile token
    let turnstileToken = window._turnstileToken ||
      document.querySelector('[name="cf-turnstile-response"]')?.value ||
      document.getElementById('cf-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

    const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
    if (!authUser && isTurnstileRequired && window.turnstile && !turnstileToken) {
      const errEl = document.getElementById('turnstile-error');
      if (errEl) errEl.style.display = 'block';
      Toast.show({
        type: 'warning',
        title: 'ক্যাপচা যাচাই আবশ্যক',
        message: 'অনুগ্রহ করে রোবট নন (Cloudflare Turnstile) যাচাই সম্পন্ন করুন।'
      });
      return;
    }
    
    if (!authUser) {
      const pin = document.getElementById('r-pin')?.value.trim();
      if (!/^\d{4}$/.test(pin)) {
        Toast.show({ type: 'error', title: 'পিন দিন', message: '৪-ডিজিটের গোপন পিন দিন।' });
        return;
      }
      
      try {
        authUser = await DataStore.signup(phone, pin, turnstileToken);
      } catch (err) {
        this.resetTurnstile();
        const msg = err.message || '';
        if (msg.includes('already registered') || msg.includes('ইতিমধ্যে')) {
          DonorModule.showPhoneDuplicateError(phone);
          Toast.show({
            type: 'error',
            title: 'নম্বরটি ইতিমধ্যে ব্যবহৃত',
            message: 'এই নম্বর দিয়ে ইতিমধ্যেই অ্যাকাউন্ট আছে। অনুগ্রহ করে লগইন করুন।',
            duration: 6000
          });
          const authPhone = document.getElementById('auth-phone');
          if (authPhone) authPhone.value = phone;
          Modal.open('auth-modal');
        } else {
          Toast.show({ type: 'error', title: 'ত্রুটি', message: msg });
        }
        return;
      }
    }

    const getVal = id => document.getElementById(id)?.value.trim() || '';
    const getChk = id => document.getElementById(id)?.checked || false;

    const donationTypes = Array.from(
      document.querySelectorAll('#r-donation-types input[type=checkbox]:checked')
    ).map(c => c.value);

    const contactPrefs = ['phone','sms','whatsapp','renewal'].filter(p =>
      document.getElementById('cp-' + p)?.checked
    );

    // Try to get real location
    let realLat = null;
    let realLng = null;
    try {
      const pos = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 5000 });
      });
      realLat = pos.coords.latitude;
      realLng = pos.coords.longitude;
    } catch (e) {
      console.warn('Geolocation failed or denied. Using null coordinates.', e.message);
    }

    const donor = {
      id: authUser.id,
      user_id: authUser.id,
      name: getVal('r-name'),
      nameEn: getVal('r-name'),
      phone: getVal('r-phone'),
      altPhone: getVal('r-alt-phone'),
      bloodGroup: getVal('r-blood-group'),
      district: getVal('r-district'),
      upazila: getVal('r-upazila'),
      area: getVal('r-area'),
      age: parseInt(getVal('r-age')) || 0,
      gender: getVal('r-gender'),
      profession: getVal('r-profession'),
      lastDonation: getVal('r-last-donation') || null,
      donationCount: parseInt(getVal('r-donation-count')) || 0,
      canDonate: getVal('r-can-donate') === 'yes',
      nextAvailable: getVal('r-next-date') || null,
      donationTypes,
      emergencyCall: getChk('r-emergency-call'),
      contactPrefs,
      verificationLevel: 1,
      trustScore: 15,
      badge: 'registered',
      availability: 'available',
      donationHistory: [],
      verificationLog: [{ type: 'mobile', date: new Date().toISOString().split('T')[0], note: 'PIN verified' }],
      joinDate: new Date().toISOString().split('T')[0],
      suspicious: false, reported: 0,
      lat: realLat,
      lng: realLng,
      turnstile_token: turnstileToken,
    };

    let createdDonor;
    try {
      createdDonor = await DataStore.addDonor(donor);
      this.resetTurnstile();
    } catch (err) {
      this.resetTurnstile();
      const msg = err.message || '';
      if (msg.includes('already registered') || msg.includes('ইতিমধ্যে')) {
        DonorModule.showPhoneDuplicateError(donor.phone);
        Toast.show({
          type: 'error',
          title: 'নিবন্ধন ব্যর্থ — ডুপ্লিকেট অ্যাকাউন্ট',
          message: 'এই ফোন নম্বর বা অ্যাকাউন্টে ইতিমধ্যে একজন রক্তদাতা নিবন্ধিত আছেন।',
          duration: 6000
        });
        const authPhone = document.getElementById('auth-phone');
        if (authPhone) authPhone.value = donor.phone;
        Modal.open('auth-modal');
      } else {
        Toast.show({ type: 'error', title: 'ত্রুটি', message: msg });
      }
      return;
    }

    // Update active user state
    await DataStore.getCurrentUser();

    Toast.show({
      type: 'success',
      title: 'নিবন্ধন সফল!',
      message: `স্বাগতম ${donor.name}! আপনার রক্তদাতা ড্যাশবোর্ডে প্রবেশ করা হচ্ছে...`,
      duration: 3500
    });

    // Auto-navigate to dashboard directly without requiring manual login
    setTimeout(() => {
      App.navigate('dashboard');
    }, 1000);
  },
};

// OTP Input auto-advance
document.addEventListener('input', (e) => {
  if (e.target.classList.contains('otp-input')) {
    const inputs = [...document.querySelectorAll('.otp-input')];
    const idx = inputs.indexOf(e.target);
    if (e.target.value && idx < inputs.length - 1) {
      inputs[idx + 1].focus();
    }
    e.target.classList.toggle('filled', !!e.target.value);
  }
});

document.addEventListener('keydown', (e) => {
  if (e.target.classList.contains('otp-input') && e.key === 'Backspace' && !e.target.value) {
    const inputs = [...document.querySelectorAll('.otp-input')];
    const idx = inputs.indexOf(e.target);
    if (idx > 0) inputs[idx - 1].focus();
  }
});

// Cloudflare Turnstile global callbacks
window.onTurnstileSuccess = function(token) {
  window._turnstileToken = token;
  const errEl = document.getElementById('turnstile-error');
  if (errEl) errEl.style.display = 'none';
};
window.onTurnstileExpired = function() {
  window._turnstileToken = null;
};

window.DonorModule = DonorModule;
