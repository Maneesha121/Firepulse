(() => {
  'use strict';

  const ROUTES = [
    { path: '/overview', label: 'Overview', id: 'fp-overview' },
    { path: '/map', label: 'Explore Map', id: 'fp-map' },
    { path: '/calendar', label: 'Fire Calendar', id: 'fp-calendar' },
    { path: '/trends', label: 'Trends & Insights', id: 'fp-trends' },
    { path: '/advanced', label: 'Advanced Analytics', id: 'fp-advanced' },
    { path: '/about', label: 'About & Methodology', id: 'fp-about' },
  ];

  const $ = (id) => document.getElementById(id);
  const routeFromLocation = () => {
    const loc = window.location.pathname.replace(/\/$/, '');
    if (loc === '' || loc === '/index.html' || loc === '/') return '/overview';
    return ROUTES.some((r) => r.path === loc) ? loc : '/overview';
  };

  function ensureRouteShell() {
    if ($('fp-nav')) return;
    const header = document.querySelector('header');
    const nav = document.createElement('nav');
    nav.id = 'fp-nav';
    nav.className = 'fp-nav';
    nav.setAttribute('aria-label', 'FirePulse navigation');
    ROUTES.forEach((route) => {
      const link = document.createElement('a');
      link.href = route.path;
      link.dataset.fpRoute = route.path;
      link.textContent = route.label;
      nav.appendChild(link);
    });
    header.appendChild(nav);

    const main = document.querySelector('main');
    if (!main) return;
    const pages = {};
    ROUTES.forEach((route) => {
      const page = document.createElement('section');
      page.id = route.id;
      page.className = 'fp-page';
      page.hidden = true;
      page.setAttribute('aria-label', route.label);
      pages[route.path] = page;
      document.body.insertBefore(page, main);
    });

    const map = $('map');
    const aoi = $('applyBox');
    const summary = $('summary');
    const cal = $('cal');
    const chart = $('chart');
    const anom = $('anom');
    const sensor = $('sensorSec');
    const qual = $('qualSec');
    const val = $('val');
    const attribution = $('attribution');
    const downloads = $('dlCsv');

    const overview = pages['/overview'];
    const stats = document.createElement('div');
    stats.id = 'fp-stats';
    stats.className = 'fp-stats';
    overview.appendChild(stats);
    const blurb = document.createElement('p');
    blurb.id = 'fp-activity-note';
    blurb.className = 'fp-activity-note';
    blurb.textContent = 'Loading hotspot activity…';
    overview.appendChild(blurb);
    if (summary) overview.appendChild(summary);
    if (downloads) overview.appendChild(downloads);

    if (map) pages['/map'].appendChild(map);
    if (aoi) pages['/map'].appendChild(aoi);
    if (cal) pages['/calendar'].appendChild(cal);
    if (chart) pages['/trends'].appendChild(chart);
    if (anom) pages['/trends'].appendChild(anom);

    const wrapAdvanced = (section, title) => {
      if (!section) return;
      const details = document.createElement('details');
      details.className = 'fp-advanced-details';
      const summary = document.createElement('summary');
      summary.textContent = title;
      details.appendChild(summary);
      details.appendChild(section);
      pages['/advanced'].appendChild(details);
    };
    wrapAdvanced(sensor, 'MODIS–VIIRS comparison and validation');
    wrapAdvanced(qual, 'Data quality and filter sensitivity');

    if (val) pages['/about'].appendChild(val);
    if (attribution) pages['/about'].appendChild(attribution);
    main.remove();
  }

  function setActiveNavigation(routePath) {
    document.querySelectorAll('.fp-nav a').forEach((link) => {
      const active = link.dataset.fpRoute === routePath;
      if (active) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  function renderOverviewStats() {
    const root = $('fp-stats');
    if (!root || typeof S === 'undefined' || typeof META === 'undefined' || !Array.isArray(S)) return;

    const range = typeof range === 'function' ? range() : [];
    const rows = S.filter((row) => row && (!range.length || (row.y >= range[0] && row.y <= range[1])));
    const combine = (key) => rows.reduce((sum, row) => sum + (Number.isFinite(Number(row[key])) ? Number(row[key]) : 0), 0);
    const hRows = rows.filter((row) => row.h != null && Number.isFinite(Number(row.h)));
    const highest = hRows.length ? hRows.reduce((best, row) => Number(row.h) > Number(best.h) ? row : best) : null;
    const assessed = rows.filter((row) => row.z != null && Number.isFinite(Number(row.z)));
    const unusual = assessed.filter((row) => Math.abs(Number(row.z)) >= 2).length;
    const latest = Array.isArray(META.months) && META.months.length ? META.months[META.months.length - 1] : 'Unavailable';

    const cards = [
      ['Observed detections', `${Math.round(combine('mod') + combine('vii')).toLocaleString()}`, 'Combined MODIS and VIIRS hotspot detections in the selected period.'],
      ['Peak activity month', highest ? highest.m : 'Not available', highest ? 'Highest harmonised activity in the selected period.' : 'No index value available.'],
      ['Historical outliers', assessed.length ? `${unusual} of ${assessed.length}` : 'Not assessed', 'Months with an atypical historical anomaly score; not a fire-danger alert.'],
      ['Latest processed month', latest, 'Latest month in the processed dataset.'],
    ];

    root.innerHTML = cards.map(([label, value, note]) => `
      <article class="fp-stat">
        <span>${label}</span>
        <strong>${value}</strong>
        <small>${note}</small>
      </article>
    `).join('');

    const note = $('fp-activity-note');
    if (note) {
      note.textContent = assessed.length
        ? `${unusual} of ${assessed.length} assessed months are unusually different from historical norms. Hotspots are satellite detections, not confirmed fire events.`
        : 'Historical comparison is not available for this selection or period. Hotspots are satellite detections, not confirmed fire events.';
    }
  }

  function navigate(routePath) {
    const path = ROUTES.some((route) => route.path === routePath) ? routePath : '/overview';
    ROUTES.forEach((route) => {
      const page = $(route.id);
      if (page) page.hidden = route.path !== path;
    });
    setActiveNavigation(path);
    history.pushState({}, '', path);
    renderOverviewStats();
    if (path === '/map' && window.map && typeof map.invalidateSize === 'function') setTimeout(() => map.invalidateSize(), 0);
    if (path === '/trends' || path === '/advanced') {
      setTimeout(() => {
        document.querySelectorAll('.fp-page:not([hidden]) canvas').forEach((canvas) => {
          if (window.Chart && typeof Chart.getChart === 'function') {
            const chartInstance = Chart.getChart(canvas);
            if (chartInstance) chartInstance.resize();
          }
        });
      }, 0);
    }
  }

  function bindNavigation() {
    document.addEventListener('click', (event) => {
      const anchor = event.target.closest('a[data-fp-route]');
      if (!anchor) return;
      event.preventDefault();
      navigate(anchor.dataset.fpRoute);
    });

    window.addEventListener('popstate', () => navigate(routeFromLocation()));
  }

  function init() {
    ensureRouteShell();
    bindNavigation();
    document.querySelectorAll('.fp-nav a').forEach((link) => {
      link.dataset.fpRoute = link.getAttribute('href');
    });
    navigate(routeFromLocation());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
