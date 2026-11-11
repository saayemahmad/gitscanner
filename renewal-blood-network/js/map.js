/* ============================================================
   RENEWAL BLOOD NETWORK — High Performance Map Module (Leaflet.js)
   ============================================================ */

const DISTRICT_COORDS = {
  'ঢাকা': [23.8103, 90.4125],
  'গাজীপুর': [23.9999, 90.4203],
  'নারায়ণগঞ্জ': [23.6238, 90.5000],
  'চট্টগ্রাম': [22.3569, 91.7832],
  'সিলেট': [24.8949, 91.8687],
  'রাজশাহী': [24.3745, 88.6042],
  'খুলনা': [22.8456, 89.5403],
  'বরিশাল': [22.7010, 90.3535],
  'ময়মনসিংহ': [24.7471, 90.4203],
  'রংপুর': [25.7439, 89.2752],
  'কুমিল্লা': [23.4682, 91.1788],
  'ফরিদপুর': [23.6071, 89.8429],
};

const MapModule = {
  map: null,
  markersLayer: null,
  tileLayer: null,
  currentFilter: '',
  _hasFallenBack: false,

  render() {
    // Schedule initialization with retry if Leaflet is loading asynchronously
    const tryInit = (retries = 15) => {
      if (typeof L !== 'undefined' && document.getElementById('map')) {
        this.initMap();
      } else if (retries > 0) {
        setTimeout(() => tryInit(retries - 1), 80);
      }
    };
    tryInit();
  },

  async initMap() {
    const mapEl = document.getElementById('map');
    if (!mapEl || typeof L === 'undefined') return;

    // If map already exists, simply invalidate size and refresh markers
    if (this.map) {
      [50, 150, 300, 500].forEach(delay => {
        setTimeout(() => {
          if (this.map) this.map.invalidateSize(true);
        }, delay);
      });
      return;
    }

    try {
      // Create Leaflet Map centered on Bangladesh
      this.map = L.map('map', {
        center: [23.75, 90.38],
        zoom: 7,
        minZoom: 6,
        maxZoom: 18,
        zoomControl: true,
        fadeAnimation: true,
        markerZoomAnimation: true
      });

      // Standard OpenStreetMap tiles - 100% reliable across all browsers & networks
      this.tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        subdomains: ['a', 'b', 'c'],
        maxZoom: 19,
        minZoom: 6,
        crossOrigin: true
      }).addTo(this.map);

      // Dedicated layer group for high-performance marker batching
      this.markersLayer = L.layerGroup().addTo(this.map);

      // Populate filter dropdown
      this.initFilterDropdown();

      // Load initial markers
      await this.loadDonorMarkers(this.currentFilter);

      // Invalidate size in multiple ticks for seamless rendering across all browser rendering engines
      [50, 150, 300, 600, 1000].forEach(delay => {
        setTimeout(() => {
          if (this.map) this.map.invalidateSize(true);
        }, delay);
      });

      // Handle window resize and mobile orientation changes
      window.addEventListener('resize', () => {
        if (this.map) {
          clearTimeout(this._resizeTimer);
          this._resizeTimer = setTimeout(() => {
            if (this.map) this.map.invalidateSize(true);
          }, 150);
        }
      });

    } catch (err) {
      console.error('Error initializing Leaflet map:', err);
    }
  },

  initFilterDropdown() {
    const filterSel = document.getElementById('map-blood-filter');
    if (!filterSel) return;

    filterSel.innerHTML = '<option value="">সব রক্তের গ্রুপ</option>';
    if (typeof BLOOD_GROUPS !== 'undefined' && Array.isArray(BLOOD_GROUPS)) {
      BLOOD_GROUPS.forEach(g => {
        const o = document.createElement('option');
        o.value = g;
        o.textContent = g;
        filterSel.appendChild(o);
      });
    }

    filterSel.onchange = async () => {
      this.currentFilter = filterSel.value;
      await this.loadDonorMarkers(this.currentFilter);
    };
  },

  async loadDonorMarkers(bloodGroup) {
    if (!this.map || !this.markersLayer) return;

    // Clear marker layer instantly
    this.markersLayer.clearLayers();

    const allDonors = await DataStore.getDonors();
    const donors = allDonors.filter(d => {
      if (bloodGroup && d.bloodGroup !== bloodGroup) return false;
      return true;
    });

    donors.forEach(d => {
      let lat = d.lat;
      let lng = d.lng;

      // Fallback to district center coordinates with slight deterministic jitter
      if (!lat || !lng) {
        const base = DISTRICT_COORDS[d.district];
        if (!base) return;
        const hash = (d.id || '').split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
        const jitterLat = ((hash % 100) - 50) * 0.0008;
        const jitterLng = (((hash * 7) % 100) - 50) * 0.0008;
        lat = base[0] + jitterLat;
        lng = base[1] + jitterLng;
      }

      const isAvailable = d.availability === 'available';
      const isSoon = d.availability === 'soon';
      const color = isAvailable ? '#059669' : isSoon ? '#D97706' : '#64748B';
      const bgColor = isAvailable ? '#ECFDF5' : isSoon ? '#FEF3C7' : '#F1F5F9';
      const avail = Utils.getAvailabilityInfo(d.availability);

      // Compact, GPU-friendly custom HTML pin
      const icon = L.divIcon({
        className: 'custom-map-donor-pin',
        html: `
          <div style="
            background:${bgColor};
            border:2px solid ${color};
            border-radius:50%;
            width:34px;height:34px;
            display:flex;align-items:center;justify-content:center;
            font-family:'Inter',sans-serif;font-weight:800;font-size:0.68rem;
            color:${color};
            box-shadow:0 2px 8px rgba(0,0,0,0.15);
            cursor:pointer;
            transition:transform 0.15s ease;
          ">
            ${d.bloodGroup}
          </div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        popupAnchor: [0, -18]
      });

      const marker = L.marker([lat, lng], { icon });

      marker.bindPopup(`
        <div style="min-width:210px;padding:4px;color:#0F172A;font-family:'Hind Siliguri',sans-serif">
          <div style="font-weight:700;font-size:1rem;margin-bottom:6px;color:#0F172A">${d.name}</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
            <span style="background:#FFF1F2;border:1px solid #FFE4E6;color:#E11D48;padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:700">${d.bloodGroup}</span>
            <span style="background:${bgColor};color:${color};padding:2px 8px;border-radius:99px;font-size:0.75rem;font-weight:600"><i class="fas fa-circle" style="font-size:0.45rem;vertical-align:middle"></i> ${avail.label}</span>
          </div>
          <div style="font-size:0.82rem;color:#475569;margin-bottom:4px"><i class="fas fa-location-dot" style="color:#E11D48"></i> ${d.area}, ${d.upazila}</div>
          <div style="font-size:0.82rem;color:#475569;margin-bottom:4px"><i class="fas fa-rotate" style="color:#0284C7"></i> ${d.donationCount} বার দান • <i class="fas fa-star" style="color:#D97706"></i> ${d.trustScore}/100</div>
          <div style="margin-top:10px">
            <button onclick="DonorModule.openContactModal('${d.id}')" style="
              background:linear-gradient(135deg,#E11D48,#BE123C);
              color:white;border:none;padding:6px 14px;border-radius:8px;
              cursor:pointer;font-size:0.82rem;width:100%;font-family:'Hind Siliguri',sans-serif;font-weight:600;display:flex;align-items:center;justify-content:center;gap:0.4rem;box-shadow:0 2px 4px rgba(225,29,72,0.2)
            "><i class="fas fa-paper-plane"></i> যোগাযোগের অনুরোধ</button>
          </div>
        </div>
      `, { maxWidth: 260 });

      this.markersLayer.addLayer(marker);
    });

    // Update count summary
    const countEl = document.getElementById('map-donor-count');
    if (countEl) countEl.textContent = `${donors.length} জন দাতা দেখানো হচ্ছে`;
  }
};

window.MapModule = MapModule;
