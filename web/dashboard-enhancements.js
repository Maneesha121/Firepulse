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
  let currentPath = null;

  function routeFromLocation() {
    const path = window.location.pathname.replace(/\/$/, '') || '/';
    if (path === '/' || path === '/index.html') return '/overview';
    return ROUTES.some((route) => route.path === path) ? path : '/overview';
  }

  function ensureRouteShell() {
    const main = document.querySelector('main');
    const header = document.querySelector('#app-shell > header') || document.querySelector('header');
    if (!main || !header) return false;

    let nav = $('fp-nav');
    if (!nav) {
      nav = document.createElement('nav');
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
    }

    const pages = {};
    ROUTES.forEach((route) => {
      let page = $(route.id);
      if (!page) {
        page = document.createElement('section');
        page.id = route.id;
        page.className = 'fp-page';
        page.hidden = true;
        page.setAttribute('aria-label', route.label);
        main.parentNode.insertBefore(page, main);
      }
      pages[route.path] = page;
    });

    // Keep original date, display, and anomaly selectors available from every route.
    let shared = $('fp-shared-controls');
    if (!shared) {
      shared = document.createElement('div');
      shared.id = 'fp-shared-controls';
      shared.className = 'fp-shared-controls';
      shared.setAttribute('aria-label', 'Shared date and display filters');
      header.insertAdjacentElement('afterend', shared);
    }
    const controlsCard = $('y0')?.closest('.card');
    if (controlsCard && controlsCard.parentElement !== shared) shared.appendChild(controlsCard);

    const moveCard = (id, path) => {
      const card = $(id)?.closest('.card');
      if (card && card.parentElement !== pages[path]) pages[path].appendChild(card);
    };
    const moveElement = (id, path) => {
      const element = $(id);
      if (element && element.parentElement !== pages[path]) pages[path].appendChild(element);
    };

    // Move whole cards so their headings, controls, status messages, and event-bound
    // descendants stay together. The original nodes/IDs are retained for inline code.
    moveElement('map', '/map');
    moveCard('applyBox', '/map');
    moveCard('summary', '/overview');
    moveCard('dlCsv', '/overview');
    moveCard('cal', '/calendar');
    moveCard('chart', '/trends');
    moveCard('anom', '/trends');

    const overview = pages['/overview'];
    if (!$('fp-stats')) {
      const stats = document.createElement('div');
      stats.id = 'fp-stats';
      stats.className = 'fp-stats';
      overview.prepend(stats);
      const note = document.createElement('p');
      note.id = 'fp-activity-note';
      note.className = 'fp-activity-note';
      note.textContent = 'Loading hotspot activity…';
      stats.after(note);
    }

    const wrapAdvanced = (id, title) => {
      const section = $(id);
      if (!section || section.closest('.fp-advanced-details')) return;
      const details = document.createElement('details');
      details.className = 'fp-advanced-details';
      const summary = document.createElement('summary');
      summary.textContent = title;
      details.append(summary, section);
      pages['/advanced'].appendChild(details);
    };
    wrapAdvanced('sensorSec', 'MODIS–VIIRS comparison and validation');
    wrapAdvanced('qualSec', 'Data quality and filter sensitivity');

    // Methodology content is a card nested inside main; preserve the entire card.
    moveCard('val', '/about');
    const attribution = $('attribution');
    if (attribution && attribution.parentElement !== pages['/about']) pages['/about'].appendChild(attribution);
    main.remove();
    return true;
  }

  function setActiveNavigation(path) {
    document.querySelectorAll('#fp-nav a[data-fp-route]').forEach((link) => {
      if (link.dataset.fpRoute === path) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function renderOverviewStats() {
    const root = $('fp-stats');
    if (!root || typeof S === 'undefined' || typeof META === 'undefined' || !Array.isArray(S)) return;

    // Avoid shadowing the global range() helper; that shadow caused a TDZ error.
    const bounds = typeof range === 'function' ? range() : [];
    const rows = S.filter((row) => row && (bounds.length < 2 || (row.y >= bounds[0] && row.y <= bounds[1])));
    const total = (key) => rows.reduce((sum, row) => sum + (Number.isFinite(Number(row[key])) ? Number(row[key]) : 0), 0);
    const indexed = rows.filter((row) => row.h != null && Number.isFinite(Number(row.h)));
    const peak = indexed.length ? indexed.reduce((best, row) => Number(row.h) > Number(best.h) ? row : best) : null;
    const assessed = rows.filter((row) => row.z != null && Number.isFinite(Number(row.z)));
    const unusual = assessed.filter((row) => Math.abs(Number(row.z)) >= 2).length;
    const latest = Array.isArray(META.months) && META.months.length ? META.months[META.months.length - 1] : 'Unavailable';
    const cards = [
      ['Observed detections', Math.round(total('mod') + total('vii')).toLocaleString(), 'Combined MODIS and VIIRS hotspot detections in the selected period.'],
      ['Peak activity month', peak ? peak.m : 'Not available', peak ? 'Highest harmonised activity in the selected period.' : 'No index value available.'],
      ['Historical outliers', assessed.length ? `${unusual} of ${assessed.length}` : 'Not assessed', 'Atypical historical anomaly scores are not fire-danger alerts.'],
      ['Latest processed month', latest, 'Latest month in the processed dataset.'],
    ];
    root.innerHTML = cards.map(([label, value, note]) => `
      <article class="fp-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>
    `).join('');
    const note = $('fp-activity-note');
    if (note) {
      note.textContent = assessed.length
        ? `${unusual} of ${assessed.length} assessed months are unusually different from historical norms. Hotspots are satellite detections, not confirmed fire events.`
        : 'Historical comparison is not available for this selection or period. Hotspots are satellite detections, not confirmed fire events.';
    }
  }

  function navigate(requestedPath, updateHistory = true) {
    const path = ROUTES.some((route) => route.path === requestedPath) ? requestedPath : '/overview';
    ROUTES.forEach((route) => {
      const page = $(route.id);
      if (page) page.hidden = route.path !== path;
    });
    setActiveNavigation(path);
    if (updateHistory && window.location.pathname !== path) window.history.pushState({}, '', path);
    document.title = `FirePulse — ${ROUTES.find((route) => route.path === path).label}`;
    renderOverviewStats();
    if (path === '/map' && window.map && typeof window.map.invalidateSize === 'function') {
      setTimeout(() => window.map.invalidateSize(), 0);
    }
    if (path === '/trends' || path === '/advanced') {
      setTimeout(() => {
        document.querySelectorAll('.fp-page:not([hidden]) canvas').forEach((canvas) => {
          const chart = window.Chart?.getChart?.(canvas);
          if (chart) chart.resize();
        });
      }, 0);
    }
    if (currentPath !== path) window.scrollTo(0, 0);
    currentPath = path;
  }

  function bindNavigation() {
    document.addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const link = event.target.closest('#fp-nav a[data-fp-route]');
      if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      navigate(link.dataset.fpRoute);
    });
    window.addEventListener('popstate', () => navigate(routeFromLocation(), false));
  }

  function init() {
    if (!ensureRouteShell()) return;
    bindNavigation();
    ['y0', 'y1', 'mode', 'baseline', 'tY', 'tM'].forEach((id) => {
      $(id)?.addEventListener('change', renderOverviewStats);
    });
    navigate(routeFromLocation(), false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
