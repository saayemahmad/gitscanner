/* ============================================================
   RENEWAL BLOOD NETWORK — Homepage Module
   ============================================================ */

const HomeModule = {
  async render() {
    await this.renderEmergencyFeed();
    await this.renderBloodGroupOverview();
    await this.renderHomeLeaderboard();
    await this.startCounters();
    this.startEmergencyTicker();
  },

  async renderHomeLeaderboard() {
    const grid = document.getElementById('home-top3-grid');
    if (!grid) return;
    const donors = await DataStore.getDonors();
    donors.sort((a, b) => (b.donationCount || 0) - (a.donationCount || 0) || (b.trustScore || 0) - (a.trustScore || 0));
    const topDonors = donors.filter(d => (d.donationCount || 0) > 0).slice(0, 3);
    if (window.LeaderboardModule && typeof LeaderboardModule.renderTop3 === 'function') {
      LeaderboardModule.renderTop3(topDonors, 'home-top3-grid');
    }
  },

  async renderEmergencyFeed() {
    const container = document.getElementById('home-emergency-feed');
    if (!container) return;

    const requests = (await DataStore.getRequests())
      .filter(r => ['verified','under_review'].includes(r.status))
      .slice(0, 6);

    if (requests.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>বর্তমানে কোনো যাচাইকৃত জরুরি অনুরোধ নেই।</p></div>';
      return;
    }

    container.innerHTML = requests.map(r => EmergencyModule.renderRequestCard(r)).join('');
  },

  async renderBloodGroupOverview() {
    const donors = await DataStore.getDonors();
    const container = document.getElementById('bg-overview-grid');
    if (!container) return;

    const groupData = {};
    BLOOD_GROUPS.forEach(g => {
      groupData[g] = { total: 0, available: 0 };
    });

    donors.forEach(d => {
      if (groupData[d.bloodGroup]) {
        groupData[d.bloodGroup].total++;
        if (d.availability === 'available') groupData[d.bloodGroup].available++;
      }
    });

    container.innerHTML = BLOOD_GROUPS.map(g => {
      const d = groupData[g];
      return `
        <div class="bg-type-card hover-lift">
          <span class="bg-type-group">${g}</span>
          <div class="bg-type-count">মোট: ${d.total} জন</div>
          <div class="bg-type-avail"><i class="fas fa-circle-check" style="color:var(--verified-green)"></i> উপলব্ধ: ${d.available} জন</div>
        </div>`;
    }).join('');
  },

  async refreshLiveStats(data) {
    const statElements = document.querySelectorAll('.hero-stat-value');
    if (!statElements.length) return;

    let total = data?.totalDonors;
    let available = data?.availableDonors;
    let districts = data?.activeDistricts;

    let donors = null;
    if (total === undefined || available === undefined || districts === undefined) {
      donors = await DataStore.getDonors();
      total = donors.length;
      available = donors.filter(d => d.canDonate || d.availability === 'available').length;
      districts = new Set(donors.map(d => d.district).filter(Boolean)).size;
    }

    const verified = donors ? donors.filter(d => d.verificationLevel >= 2).length : Math.round(total * 0.7);
    const stats = [total, verified, available, districts];

    statElements.forEach((el, idx) => {
      if (stats[idx] !== undefined) {
        const targetVal = stats[idx];
        const currentVal = parseInt(el.textContent) || 0;
        if (currentVal !== targetVal) {
          el.dataset.target = targetVal;
          let curr = currentVal;
          const diff = targetVal - currentVal;
          const steps = Math.min(Math.abs(diff), 20) || 1;
          const stepVal = diff / steps;
          let count = 0;
          const timer = setInterval(() => {
            count++;
            curr += stepVal;
            el.textContent = Math.round(curr);
            if (count >= steps) {
              el.textContent = targetVal;
              clearInterval(timer);
            }
          }, 25);
        }
      }
    });
  },

  async startCounters() {
    await this.refreshLiveStats();
  },

  async startEmergencyTicker() {
    // Show the most recent verified emergency request once after 5s
    setTimeout(async () => {
      const reqs = await DataStore.getRequests();
      const latest = reqs.filter(r => r.status === 'verified').sort((a,b) => new Date(b.submittedAt) - new Date(a.submittedAt))[0];
      if (latest) {
        Toast.show({
          type: 'emergency',
          title: `জরুরি: ${latest.bloodGroup} রক্ত প্রয়োজন`,
          message: `${latest.hospital}, ${latest.district} — ${latest.units} ব্যাগ। এখনই সাহায্য করুন!`,
          duration: 8000
        });
      }
    }, 5000);
  }
};

/* ============================================================
   RENEWAL BLOOD NETWORK — Dashboard Module
   ============================================================ */

const DashboardModule = {
  async render() {
    const layout = document.getElementById('dashboard-layout') || document.querySelector('.dashboard-layout');
    const authPrompt = document.getElementById('dashboard-auth-prompt');
    const newPrompt = document.getElementById('dashboard-newuser-prompt');

    // Check if logged in
    let user = await DataStore.getCurrentUser();
    if (!user) {
      if (layout) layout.style.display = 'none';
      if (newPrompt) newPrompt.style.display = 'none';
      if (authPrompt) authPrompt.style.display = 'block';
      return;
    }

    if (user.isNew) {
      if (layout) layout.style.display = 'none';
      if (authPrompt) authPrompt.style.display = 'none';
      if (newPrompt) {
        newPrompt.style.display = 'block';
        const phoneEl = document.getElementById('dashboard-newuser-phone');
        if (phoneEl) phoneEl.textContent = user.phone || '';
      }
      return;
    }

    // Authenticated donor — reveal layout and populate
    if (authPrompt) authPrompt.style.display = 'none';
    if (newPrompt) newPrompt.style.display = 'none';
    if (layout) layout.style.display = '';

    this.renderProfile(user);
    this.renderDonationHistory(user);
    this.renderNotifications(user);
    this.renderNextEligible(user);
    this.renderVerificationLog(user);
  },

  renderProfile(user) {
    const el = id => document.getElementById(id);

    if (el('dash-name')) el('dash-name').textContent = user.name;
    if (el('dash-initials')) el('dash-initials').textContent = user.name.charAt(0);
    if (el('dash-blood')) el('dash-blood').textContent = user.bloodGroup;
    if (el('dash-location')) el('dash-location').textContent = `${user.area}, ${user.upazila}`;
    if (el('dash-trust')) el('dash-trust').textContent = user.trustScore;
    if (el('dash-join')) el('dash-join').textContent = Utils.formatDate(user.joinDate);
    if (el('dash-donations')) el('dash-donations').textContent = user.donationCount;

    // Trust score bar
    const bar = el('dash-trust-bar');
    if (bar) setTimeout(() => bar.style.width = user.trustScore + '%', 300);

    // Verification chips
    const levels = [
      { label: '<i class="fas fa-mobile"></i> মোবাইল যাচাই', done: user.verificationLevel >= 1 },
      { label: '<i class="fas fa-id-card"></i> পরিচয় যাচাই', done: user.verificationLevel >= 2 },
      { label: '<i class="fas fa-droplet"></i> রক্তের গ্রুপ যাচাই', done: user.verificationLevel >= 3 },
      { label: '<i class="fas fa-star"></i> রিনিউয়েল যাচাই', done: user.verificationLevel >= 4 },
    ];

    const verChips = el('dash-verify-chips');
    if (verChips) {
      verChips.innerHTML = levels.map(l => `
        <div class="verif-item">
          <span class="label">${l.label}</span>
          <span class="${l.done ? 'status-ok' : 'status-no'}">${l.done ? '✓' : '—'}</span>
        </div>`).join('');
    }

    // Badge
    const badgeEl = el('dash-badge');
    const badgeInfo = Utils.getBadgeInfo(user.badge);
    if (badgeEl) {
      badgeEl.innerHTML = badgeInfo.label;
      badgeEl.className = `donor-badge ${badgeInfo.class}`;
    }

    // Google Verified Badge in Dashboard
    const gBadge = el('dash-google-badge');
    if (gBadge) {
      const email = user.email || user.oauth_email;
      if (user.oauthProvider === 'google' || email) {
        gBadge.style.display = 'inline-flex';
        gBadge.innerHTML = `<i class="fa-brands fa-google"></i> Google ভেরিফাইড`;
      } else {
        gBadge.style.display = 'none';
      }
    }

    // Availability
    document.querySelectorAll('.avail-option').forEach(opt => {
      opt.classList.toggle('selected-avail', opt.dataset.avail === user.availability);
      opt.onclick = async () => {
        await DataStore.updateDonor(user.id, { availability: opt.dataset.avail });
        // Update cached user locally
        user.availability = opt.dataset.avail;
        document.querySelectorAll('.avail-option').forEach(o => o.classList.remove('selected-avail'));
        opt.classList.add('selected-avail');
        Toast.show({ type: 'success', title: 'অবস্থা আপডেট', message: `অবস্থা "${opt.textContent.trim()}" করা হয়েছে।` });
      };
    });
  },

  renderDonationHistory(user) {
    const tbody = document.getElementById('donation-history-body');
    if (!tbody) return;

    const history = user.donationHistory || [];
    if (history.length === 0) {
      tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-muted);font-family:var(--font-bn)">কোনো ইতিহাস নেই</td></tr>`;
      return;
    }

    tbody.innerHTML = history.slice().reverse().map((h, i) => `
      <tr>
        <td>${Utils.formatDate(h.date)}</td>
        <td>${h.location}</td>
        <td><span class="status-badge status-completed"><i class="fas fa-check"></i> সম্পন্ন</span></td>
      </tr>`).join('');
  },

  renderNextEligible(user) {
    const el = document.getElementById('dash-next-eligible');
    if (!el) return;

    if (!user.nextAvailable) {
      el.innerHTML = `<div class="next-eligible-display"><div class="date-big" style="color:var(--verified-green)"><i class="fas fa-circle-check"></i> এখনই দিতে পারবেন</div></div>`;
      return;
    }

    const next = new Date(user.nextAvailable);
    const now = new Date();
    const canDonate = next <= now;

    el.innerHTML = `
      <div class="next-eligible-display" style="${canDonate ? '' : 'background:rgba(229,57,53,0.1);border-color:rgba(229,57,53,0.2)'}">
        <div style="font-size:0.85rem;color:var(--text-muted);font-family:var(--font-bn);margin-bottom:0.4rem">পরবর্তী রক্তদান</div>
        <div class="date-big" style="color:${canDonate ? 'var(--verified-green)' : 'var(--pending-amber)'}">
          ${canDonate ? '<i class="fas fa-circle-check"></i> এখনই দিতে পারবেন' : Utils.formatDate(user.nextAvailable)}
        </div>
        ${!canDonate ? '<div style="font-size:0.8rem;color:var(--text-muted);font-family:var(--font-bn);margin-top:0.3rem">শেষ রক্তদানের ৩ মাস পর</div>' : ''}
      </div>`;
  },

  renderVerificationLog(user) {
    const container = document.getElementById('dash-verify-log');
    if (!container) return;
    const log = user.verificationLog || [];
    if (log.length === 0) {
      container.innerHTML = '<p class="text-muted font-bn">কোনো যাচাই লগ নেই</p>';
      return;
    }
    container.innerHTML = log.map(l => `
      <div style="display:flex;align-items:center;gap:0.75rem;padding:0.6rem 0;border-bottom:1px solid var(--border)">
        <span style="font-size:1.1rem;color:var(--blood-light)">${l.type === 'mobile' ? '<i class="fas fa-mobile"></i>' : l.type === 'identity' ? '<i class="fas fa-id-card"></i>' : l.type === 'bloodGroup' ? '<i class="fas fa-droplet"></i>' : '<i class="fas fa-star"></i>'}</span>
        <div style="flex:1">
          <div style="font-family:var(--font-bn);font-size:0.85rem;color:var(--text-primary)">${Utils.getVerificationLabel(['','mobile','identity','bloodGroup','renewal'].indexOf(l.type))}</div>
          <div style="font-size:0.75rem;color:var(--text-muted)">${l.date} ${l.note ? '— '+l.note : ''}</div>
        </div>
        <span style="color:var(--verified-green);font-weight:700"><i class="fas fa-check"></i></span>
      </div>`).join('');
  },

  async renderNotifications(user) {
    const container = document.getElementById('dash-notifications');
    if (!container) return;

    let notifs = [];

    // Check if eligible to donate
    if (user && user.canDonate) {
      notifs.push({ icon: '<i class="fas fa-calendar-check" style="color:#00E5FF"></i>', title: 'রক্তদানের সুযোগ', body: 'আপনি এখন রক্ত দিতে পারবেন। আজই একজনের জীবন বাঁচান।', time: 'এখন', type: 'info' });
    }

    // Fetch real emergency requests in their district
    const reqs = await DataStore.getRequests();
    const localReqs = reqs.filter(r => r.status === 'verified' && r.district === user.district);
    
    localReqs.slice(0, 3).forEach(r => {
      notifs.push({ 
        icon: '<i class="fas fa-triangle-exclamation" style="color:#FF1744"></i>', 
        title: `জরুরি ${r.bloodGroup} রক্তের অনুরোধ`, 
        body: `আপনার জেলায় (${r.district}) রক্তের দরকার। ${r.hospital}। ${r.units} ব্যাগ।`, 
        time: Utils.formatDate(r.submittedAt), 
        type: 'emergency' 
      });
    });

    if (notifs.length === 0) {
      container.innerHTML = '<p class="text-muted font-bn">কোনো নতুন নোটিফিকেশন নেই</p>';
      return;
    }

    container.innerHTML = notifs.map(n => `
      <div style="display:flex;align-items:flex-start;gap:0.75rem;padding:0.75rem 0;border-bottom:1px solid var(--border)">
        <span style="font-size:1.2rem;flex-shrink:0;width:24px;text-align:center">${n.icon}</span>
        <div style="flex:1">
          <div style="font-family:var(--font-bn);font-weight:700;font-size:0.9rem;color:var(--text-primary)">${n.title}</div>
          <div style="font-family:var(--font-bn);font-size:0.82rem;color:var(--text-secondary);margin-top:0.2rem">${n.body}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.3rem">${n.time}</div>
        </div>
      </div>`).join('');
  }
};

window.HomeModule = HomeModule;
window.DashboardModule = DashboardModule;
