/* ============================================================
   RENEWAL ADMIN — Core App
   ============================================================ */

Object.assign(Utils, {
  formatDate(d) {
    if (!d) return 'N/A';
    const date = new Date(d);
    return date.toLocaleDateString('bn-BD', { day: 'numeric', month: 'long', year: 'numeric' });
  },
  getBadgeInfo(badge) {
    const badges = {
      'registered': { label: 'নিবন্ধিত', class: 'badge-registered' },
      'bronze': { label: 'ব্রোঞ্জ দাতা', class: 'badge-bronze' },
      'silver': { label: 'সিলভার দাতা', class: 'badge-silver' },
      'gold': { label: 'গোল্ড দাতা', class: 'badge-gold' },
      'lifesaver': { label: 'Life Saver', class: 'badge-lifesaver' },
    };
    return badges[badge] || badges['registered'];
  },
  getStatusBadge(status) {
    switch (status) {
      case 'pending': return { label: 'অপেক্ষমাণ', class: 'status-pending', icon: '<i class="fas fa-clock"></i>' };
      case 'under_review': return { label: 'পর্যালোচনাধীন', class: 'status-review', icon: '<i class="fas fa-magnifying-glass"></i>' };
      case 'verified': return { label: 'যাচাইকৃত (লাইভ)', class: 'status-verified', icon: '<i class="fas fa-check"></i>' };
      case 'completed': return { label: 'সম্পন্ন', class: 'status-completed', icon: '<i class="fas fa-circle-check"></i>' };
      case 'rejected': return { label: 'বাতিল', class: 'status-rejected', icon: '<i class="fas fa-xmark"></i>' };
      default: return { label: status, class: '', icon: '' };
    }
  },
  getVerificationLabel(level) {
    const labels = ['নিবন্ধিত', 'মোবাইল ভেরিফাইড', 'পরিচয় ভেরিফাইড', 'রক্তের গ্রুপ ভেরিফাইড', 'রিনিউয়েল ভেরিফাইড'];
    return labels[level] || 'অজানা';
  }
});

const Toast = {
  show({ type = 'info', title = '', message = '', duration = 4000 }) {
    const container = document.getElementById('toast-container') || (() => {
      const c = document.createElement('div');
      c.id = 'toast-container';
      c.className = 'toast-container';
      document.body.appendChild(c);
      return c;
    })();

    const icons = {
      success: '<i class="fas fa-circle-check" style="color:var(--verified-green)"></i>',
      error: '<i class="fas fa-circle-xmark" style="color:var(--blood-red)"></i>',
      info: '<i class="fas fa-circle-info" style="color:var(--blood-light)"></i>',
      emergency: '<i class="fas fa-triangle-exclamation" style="color:var(--blood-red)"></i>'
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <div class="toast-icon">${icons[type]}</div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-message">${message}</div>
      </div>
    `;

    container.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);

    if (duration > 0) {
      setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
      }, duration);
    }
    return toast;
  }
};

window.Utils = Utils;
window.Toast = Toast;

const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const el = entry.target;
      const target = +el.dataset.target;
      let c = 0;
      const increment = target / 40;
      const updateCounter = () => {
        c += increment;
        if (c < target) {
          el.innerText = Math.ceil(c);
          requestAnimationFrame(updateCounter);
        } else {
          el.innerText = target;
        }
      };
      updateCounter();
      counterObserver.unobserve(el);
    }
  });
}, { threshold: 0.5 });
window.counterObserver = counterObserver;
