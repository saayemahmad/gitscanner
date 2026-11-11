/* ============================================================
   RENEWAL BLOOD NETWORK — Emergency Request Module
   ============================================================ */

const EmergencyModule = {
  currentStep: 1,

  async render() {
    this.currentStep = 1;
    this.updateWizardStep(1);
    this.populateSelects();
    await this.renderActiveRequests();
    this.renderTurnstile();
    
    // Listen for realtime updates
    if (!this._subscribed) {
      DataStore.subscribeToChanges(() => {
        this.renderActiveRequests();
      });
      this._subscribed = true;
    }
  },

  populateSelects() {
    const bgSel = document.getElementById('eq-blood-group');
    if (bgSel && bgSel.options.length <= 1) {
      BLOOD_GROUPS.forEach(g => {
        const o = document.createElement('option');
        o.value = g; o.textContent = g;
        bgSel.appendChild(o);
      });
    }
    const distSel = document.getElementById('eq-district');
    if (distSel && distSel.options.length <= 1) {
      Object.keys(BD_LOCATIONS).forEach(d => {
        const o = document.createElement('option');
        o.value = d; o.textContent = d;
        distSel.appendChild(o);
      });
    }
    if (distSel) {
      distSel.onchange = () => {
        const upSel = document.getElementById('eq-upazila');
        if (!upSel) return;
        upSel.innerHTML = '<option value="">উপজেলা বেছে নিন</option>';
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
  },

  updateWizardStep(step) {
    this.currentStep = step;
    document.querySelectorAll('#emergency-wizard .wizard-step').forEach((el, i) => {
      const s = i + 1;
      el.classList.toggle('active', s === step);
      el.classList.toggle('done', s < step);
    });
    document.querySelectorAll('#emergency-form-section .wizard-pane').forEach((pane, i) => {
      pane.classList.toggle('active', i + 1 === step);
    });
    if (step === 1) {
      this.renderTurnstile();
    }
  },

  nextStep() {
    if (!this.validateStep(this.currentStep)) return;
    if (this.currentStep === 2) {
      this.goToStep3();
      return;
    }
    this.updateWizardStep(this.currentStep + 1);
  },

  prevStep() {
    if (this.currentStep > 1) this.updateWizardStep(this.currentStep - 1);
  },

  validateStep(step) {
    if (step === 1) {
      const patient = document.getElementById('eq-patient')?.value.trim();
      const bg = document.getElementById('eq-blood-group')?.value;
      const units = document.getElementById('eq-units')?.value;
      if (!patient || !bg || !units) {
        Toast.show({ type: 'error', title: 'তথ্য অসম্পূর্ণ', message: 'সব প্রয়োজনীয় তথ্য দিন।' });
        return false;
      }

      // Check Cloudflare Turnstile token on Step 1
      const turnstileToken = this._eqTurnstileToken ||
        document.getElementById('eq-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

      const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
      if (isTurnstileRequired && window.turnstile && !turnstileToken) {
        const errEl = document.getElementById('eq-turnstile-error');
        if (errEl) errEl.style.display = 'block';
        Toast.show({
          type: 'warning',
          title: 'ক্যাপচা যাচাই প্রয়োজন',
          message: 'অনুগ্রহ করে আমি রোবট নই (Cloudflare Turnstile) যাচাইটি সম্পন্ন করুন।'
        });
        return false;
      }
    }
    if (step === 2) {
      const hospital = document.getElementById('eq-hospital')?.value.trim();
      const phone = document.getElementById('eq-contact')?.value.trim();
      if (!hospital || !phone) {
        Toast.show({ type: 'error', title: 'তথ্য অসম্পূর্ণ', message: 'হাসপাতাল ও যোগাযোগ নম্বর দিন।' });
        return false;
      }
    }
    return true;
  },

  async goToStep3() {
    // Check if already logged in
    const user = await DataStore.getCurrentUser();
    if (user && !user.isNew) {
      // Logged in, skip PIN step and submit directly
      this.submitRequestWithAuth();
      return;
    }
    this.updateWizardStep(3);
  },

  _eqTurnstileWidgetId: null,
  _eqTurnstileToken: null,

  renderTurnstile() {
    const container = document.getElementById('eq-turnstile-container');
    if (!container) return;

    const renderFn = () => {
      if (window.turnstile && typeof window.turnstile.render === 'function') {
        if (container.querySelector('iframe')) return;
        try {
          const siteKey = (DataStore.config && DataStore.config.turnstileSiteKey) || '1x00000000000000000000AA';
          container.innerHTML = '';
          this._eqTurnstileWidgetId = window.turnstile.render(container, {
            sitekey: siteKey,
            callback: (token) => {
              this._eqTurnstileToken = token;
              const errEl = document.getElementById('eq-turnstile-error');
              if (errEl) errEl.style.display = 'none';
            },
            'expired-callback': () => {
              this._eqTurnstileToken = null;
            },
            theme: 'light'
          });
        } catch (e) {
          console.warn('[Turnstile Emergency] render error:', e.message);
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
    this._eqTurnstileToken = null;
    if (window.turnstile && typeof window.turnstile.reset === 'function') {
      try {
        if (this._eqTurnstileWidgetId !== null) {
          window.turnstile.reset(this._eqTurnstileWidgetId);
        } else {
          window.turnstile.reset('#eq-turnstile-container');
        }
      } catch (_) {}
    }
  },

  async submitRequestWithAuth() {
    let authUser = await DataStore.getCurrentUser();
    const phone = document.getElementById('eq-contact')?.value.trim();
    
    if (!authUser) {
      const pin = document.getElementById('eq-pin')?.value.trim();
      if (!/^\d{4}$/.test(pin)) {
        Toast.show({ type: 'error', title: 'পিন দিন', message: '৪-ডিজিটের গোপন পিন দিন।' });
        return;
      }

      // Verify Cloudflare Turnstile token for Emergency PIN submission
      const turnstileToken = this._eqTurnstileToken ||
        document.getElementById('eq-turnstile-container')?.querySelector('input[type="hidden"]')?.value || '';

      const isTurnstileRequired = DataStore.config ? DataStore.config.turnstileEnabled : true;
      if (isTurnstileRequired && window.turnstile && !turnstileToken) {
        const errEl = document.getElementById('eq-turnstile-error');
        if (errEl) errEl.style.display = 'block';
        Toast.show({
          type: 'warning',
          title: 'ক্যাপচা যাচাই প্রয়োজন',
          message: 'অনুগ্রহ করে আমি রোবট নই (Cloudflare Turnstile) যাচাইটি সম্পন্ন করুন।'
        });
        return;
      }
      
      try {
        authUser = await DataStore.signup(phone, pin, turnstileToken);
      } catch (err) {
        if (err.message.includes('already registered')) {
          Toast.show({ type: 'error', title: 'নম্বরটি ব্যবহৃত', message: 'এই নম্বর দিয়ে ইতিমধ্যেই অ্যাকাউন্ট আছে। লগইন করুন।' });
        } else {
          Toast.show({ type: 'error', title: 'ত্রুটি', message: err.message });
        }
        return;
      }
    }

    this.submitRequest(authUser);
  },

  async submitRequest(authUser) {
    const getVal = id => document.getElementById(id)?.value.trim() || '';
    const request = {
      id: DataStore.generateId('R'),
      userId: authUser ? authUser.id : null,
      patientName: getVal('eq-patient'),
      bloodGroup: getVal('eq-blood-group'),
      units: getVal('eq-units'),
      hospital: getVal('eq-hospital'),
      district: getVal('eq-district'),
      upazila: getVal('eq-upazila'),
      neededDate: getVal('eq-date'),
      neededTime: getVal('eq-time'),
      attendantName: getVal('eq-attendant'),
      contact: getVal('eq-contact'),
      reason: getVal('eq-reason'),
      status: 'pending',
      submittedAt: new Date().toISOString(),
      verifiedAt: null,
      reported: 0,
      verificationNote: '',
    };

    await DataStore.addRequest(request);

    // Show success panel
    document.getElementById('emergency-form-section').style.display = 'none';
    document.getElementById('emergency-success-section').style.display = 'block';
    document.getElementById('es-patient').textContent = request.patientName;
    document.getElementById('es-blood').textContent = request.bloodGroup;
    document.getElementById('es-id').textContent = request.id;
    document.getElementById('es-hospital').textContent = request.hospital;

    Toast.show({
      type: 'success',
      title: 'অনুরোধ জমা হয়েছে!',
      message: 'Renewal Foundation শীঘ্রই যাচাই করবে।',
      duration: 6000
    });
  },

  async renderActiveRequests() {
    const container = document.getElementById('active-requests-list');
    if (!container) return;

    container.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-spinner fa-spin"></i></div><p>লোড হচ্ছে...</p></div>';

    const requests = (await DataStore.getRequests())
      .filter(r => ['verified','under_review','pending'].includes(r.status))
      .slice(0, 8);

    if (requests.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-circle-check"></i></div><p>বর্তমানে কোনো জরুরি অনুরোধ নেই</p></div>';
      return;
    }

    container.innerHTML = requests.map(r => this.renderRequestCard(r)).join('');
  },

  renderRequestCard(r) {
    const statusInfo = Utils.getStatusBadge(r.status);
    const time = r.neededTime ? Utils.formatTime12(r.neededTime) : '';
    const isUrgent = r.status === 'verified' && r.neededDate === new Date().toISOString().split('T')[0];
    
    // Formatting Location
    const locationStr = [r.upazila, r.district].filter(Boolean).join(', ');

    return `
    <div class="emergency-card ${isUrgent ? 'anim-glowRed' : ''}">
      <div class="e-header">
        <div>
          <span class="emergency-badge"><span class="pulse-dot"></span> <i class="fas fa-triangle-exclamation"></i> জরুরি</span>
        </div>
        <span class="status-badge ${statusInfo.class}">${statusInfo.icon} ${statusInfo.label}</span>
      </div>

      <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem">
        <span class="bg-badge large">${r.bloodGroup}</span>
        <div>
          <div class="e-title">${r.patientName} — ${r.units} ব্যাগ রক্ত প্রয়োজন</div>
        </div>
      </div>

      <div class="e-details">
        <div class="e-detail"><span class="icon"><i class="fas fa-hospital"></i></span>${r.hospital}</div>
        ${locationStr ? `<div class="e-detail"><span class="icon"><i class="fas fa-location-dot"></i></span>${locationStr}</div>` : ''}
        ${r.reason && r.reason !== 'null' ? `<div class="e-detail"><span class="icon"><i class="fas fa-file-lines"></i></span>${r.reason}</div>` : ''}
        <div class="e-detail"><span class="icon"><i class="fas fa-clock"></i></span>প্রয়োজন: ${r.neededDate && r.neededDate !== 'null' ? Utils.formatDate(r.neededDate) : 'যত দ্রুত সম্ভব'}${time ? ' (সময়: '+time+')' : ''}</div>
      </div>

      <div class="e-footer">
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
          ${r.status === 'verified' ? `<button class="btn btn-primary btn-sm" onclick="DonorModule.openContactForRequest('${r.id}')"><i class="fas fa-droplet"></i> রক্ত দিতে চাই</button>` : ''}
          <button class="btn btn-ghost btn-sm" onclick="EmergencyModule.reportRequest('${r.id}')"><i class="fas fa-flag"></i> রিপোর্ট</button>
        </div>
        <span style="font-size:0.75rem;color:var(--text-muted)">ID: ${r.id}</span>
      </div>
    </div>`;
  },

  async reportRequest(id) {
    const reqs = await DataStore.getRequests();
    const req = reqs.find(r => r.id === id);
    const newCount = ((req && req.reported) || 0) + 1;
    await DataStore.updateRequest(id, { reported: newCount });
    Toast.show({ type: 'warning', title: 'রিপোর্ট করা হয়েছে', message: 'অনুরোধটি পর্যালোচনার জন্য চিহ্নিত করা হয়েছে।' });
  },
};

window.EmergencyModule = EmergencyModule;
