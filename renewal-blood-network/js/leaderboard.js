/* ============================================================
   RENEWAL BLOOD NETWORK — Leaderboard Module
   ============================================================ */

const LeaderboardModule = {
  async render() {
    const donors = await DataStore.getDonors();
    // Sort by donationCount descending, then trustScore descending
    donors.sort((a, b) => (b.donationCount || 0) - (a.donationCount || 0) || (b.trustScore || 0) - (a.trustScore || 0));
    
    // Top donors with at least 1 donation
    const topDonors = donors.filter(d => (d.donationCount || 0) > 0);
    
    this.renderTop3(topDonors.slice(0, 3), 'top3-grid');
    this.renderList(topDonors.slice(3, 25));
  },

  renderTop3(donors, containerId = 'top3-grid') {
    const grid = document.getElementById(containerId);
    if (!grid) return;
    
    if (!donors || donors.length === 0) {
      grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--text-muted);font-family:var(--font-bn)">এখনো কোনো রক্তদাতা নেই। প্রথম রক্তদাতা হয়ে লিডারবোর্ডে যুক্ত হোন!</div>';
      return;
    }

    // Reorder: 2nd, 1st, 3rd for podium effect
    const podium = [];
    if (donors[1]) podium.push({ ...donors[1], rank: 2 });
    if (donors[0]) podium.push({ ...donors[0], rank: 1 });
    if (donors[2]) podium.push({ ...donors[2], rank: 3 });

    grid.innerHTML = podium.map(d => {
      const parts = d.name.trim().split(' ');
      const maskedName = parts[0].charAt(0) + '*** ' + (parts.slice(1).join(' ') || '');
      const badgeInfo = (typeof Utils !== 'undefined' && Utils.getBadgeInfo) ? Utils.getBadgeInfo(d.badge) : { label: '' };
      return `
        <div class="top3-card rank-${d.rank}">
          <div class="rank-badge">${d.rank}</div>
          ${d.rank === 1 ? '<div class="rank-crown"><i class="fas fa-crown"></i></div>' : ''}
          <div class="top3-avatar">${d.name.charAt(0)}</div>
          <div class="top3-name" title="${d.name}">${maskedName}</div>
          <div class="top3-blood"><i class="fas fa-droplet" style="font-size:0.75rem"></i> ${d.bloodGroup}</div>
          <div class="top3-count">${d.donationCount} বার রক্তদান</div>
          <div class="top3-location"><i class="fas fa-location-dot"></i> ${d.district} ${d.upazila ? '• ' + d.upazila : ''}</div>
          ${badgeInfo.label ? `<div style="margin-top:0.5rem;font-size:0.8rem">${badgeInfo.label}</div>` : ''}
        </div>
      `;
    }).join('');
  },

  renderList(donors) {
    const list = document.getElementById('full-leaderboard');
    if (!list) return;
    
    if (!donors || donors.length === 0) {
      list.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-muted);font-family:var(--font-bn)">কোনো অতিরিক্ত দাতা নেই</div>';
      return;
    }

    list.innerHTML = donors.map((d, i) => {
      const rank = i + 4;
      const parts = d.name.trim().split(' ');
      const maskedName = parts[0].charAt(0) + '*** ' + (parts.slice(1).join(' ') || '');
      const badgeInfo = (typeof Utils !== 'undefined' && Utils.getBadgeInfo) ? Utils.getBadgeInfo(d.badge) : { label: '' };
      return `
        <div class="leaderboard-item">
          <div class="lb-rank">${rank}</div>
          <div class="lb-avatar">${d.name.charAt(0)}</div>
          <div class="lb-info">
            <div class="lb-name">
              <span>${maskedName}</span>
              ${badgeInfo.label ? `<span style="font-size:0.78rem;font-weight:normal">${badgeInfo.label}</span>` : ''}
            </div>
            <div class="lb-meta">
              <span><i class="fas fa-location-dot" style="font-size:0.75rem"></i> ${d.district}</span>
              <span>•</span>
              <span class="bg-badge" style="font-size:0.75rem;padding:0.15rem 0.5rem">${d.bloodGroup}</span>
              <span>•</span>
              <span style="color:var(--verified-green)"><i class="fas fa-star" style="color:#F59E0B"></i> Trust: ${d.trustScore}/100</span>
            </div>
          </div>
          <div class="lb-stats">
            <div class="lb-count">${d.donationCount}</div>
            <div class="lb-unit">বার রক্তদান</div>
          </div>
        </div>
      `;
    }).join('');
  }
};

window.LeaderboardModule = LeaderboardModule;
