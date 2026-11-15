/* Multi-route organizer for the existing dashboard. Existing controls, IDs and analysis stay intact. */
(() => {
  'use strict';
  const ROUTES = [
    { path: '/overview', label: 'Overview', id: 'fp-overview' },
    { path: '/map', label: 'Explore Map', id: 'fp-map' },
    { path: '/calendar', label: 'Fire Calendar', id: 'fp-calendar' },
    { path: '/trends', label: 'Trends & Insights', id: 'fp-trends' },
    { path: '/advanced', label: 'Advanced Analytics', id: 'fp-advanced' },
    { path: '/about', label: 'About & Methodology', id: 'fp-about' }
  ];
  const $ = id => document.getElementById(id);
  const card = id => { const el = $(id); return el && el.closest('.card'); };

  function build() {
    const main = document.querySelector('main'), header = document.querySelector('header');
    if (!main || !header || $('fp-overview')) return;

    const nav = document.createElement('nav');
    nav.className = 'fp-nav'; nav.setAttribute('aria-label', 'Main navigation');
    ROUTES.forEach(route => {
      const a = document.createElement('a'); a.href = route.path; a.textContent = route.label;
      a.dataset.fpRoute = route.path; nav.appendChild(a);
    });
    header.appendChild(nav);

    const pages = {};
    for (const route of ROUTES) {
      const page = document.createElement('section');
      page.className = 'fp-page'; page.id = route.id; page.hidden = true;
      page.setAttribute('aria-labelledby', `${route.id}-heading`);
      const heading = document.createElement('header'); heading.className = 'fp-page-heading';
      const h = document.createElement('h2'); h.id = `${route.id}-heading`; h.textContent = route.label;
      heading.appendChild(h); page.appendChild(heading); main.parentNode.insertBefore(page, main);
      pages[route.path] = page;
    }

    const put = (route, node) => { if (node) pages[route].appendChild(node); };
    const summary = card('summary'), dateControls = card('y0'), calendar = card('cal');
    const chart = card('chart'), anomaly = card('anom'), downloads = card('dlCsv');
    const aoi = card('applyBox'), method = card('val');
    const map = $('map'), sensor = $('sensorSec'), quality = $('qualSec'), attribution = $('attribution');

    // Overview: only real counts, a plain-language interpretation and a small set of headline values.
    const overview = pages['/overview'];
    const stats = document.createElement('div'); stats.id = 'fp-stats'; stats.className = 'fp-stats';
    overview.appendChild(stats);
    const explainer = document.createElement('p'); explainer.id = 'fp-activity-note';
    explainer.className = 'fp-activity-note';
    explainer.textContent = 'Loading observed satellite activity…'; overview.appendChild(explainer);
    put('/overview', summary);
    put('/overview', downloads);

    put('/map', map); put('/map', aoi);
    put('/calendar', dateControls); put('/calendar', calendar);
    put('/trends', chart); put('/trends', anomaly);

    // Preserve all advanced visualization/controls while keeping them off the ordinary-user pages.
    [sensor, quality].forEach((section, index) => {
      if (!section) return;
      const details = document.createElement('details'); details.className = 'fp-advanced-details';
      const label = document.createElement('summary');
      label.textContent = index === 0 ? 'MODIS–VIIRS comparison and validation' : 'Data quality and filter sensitivity';
      details.append(label, section); pages['/advanced'].appendChild(details);
      details.addEventListener('toggle', () => {
        if (!details.open || !window.Chart || typeof Chart.getChart !== 'function') return;
        details.querySelectorAll('canvas').forEach(canvas => {
          const instance = Chart.getChart(canvas); if (instance) instance.resize();
        });
      });
    });
    put('/about', method); put('/about', attribution);

    // Move the existing page content, retaining the original script's IDs and event handlers.
    main.remove();
    const initial = location.pathname === '/' || location.pathname === '/index.html' ? '/overview' : location.pathname;
    navigate(ROUTES.some(r => r.path === initial) ? initial : '/overview', false);
    document.addEventListener('click', event => {
      const link = event.target.closest('a[data-fp-route]');
      if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault(); navigate(link.dataset.fpRoute, true);
    });
    window.addEventListener('popstate', () => {
      const path = location.pathname === '/' || location.pathname === '/index.html' ? '/overview' : location.pathname;
      navigate(ROUTES.some(r => r.path === path) ? path : '/overview', false);
    });
    document.addEventListener('change', event => {
      if (['y0', 'y1', 'mode', 'baseline', 'tY', 'tM'].includes(event.target.id)) updateOverview();
    });
    const calendarRoot = $('cal');
    if (calendarRoot && window.MutationObserver) new MutationObserver(updateOverview).observe(calendarRoot, { childList: true, subtree: true });
  }

  function navigate(path, push) {
    const route = ROUTES.find(item => item.path === path) || ROUTES[0];
    ROUTES.forEach(item => {
      const page = $(item.id); if (page) page.hidden = item.path !== route.path;
    });
    document.querySelectorAll('.fp-nav a').forEach(a => {
      if (a.dataset.fpRoute === route.path) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    if (push && location.pathname !== route.path) history.pushState({}, '', route.path);
    document.title = `FirePulse — ${route.label}`;
    if (route.path === '/map' && window.map && typeof map.invalidateSize === 'function') setTimeout(() => map.invalidateSize(), 0);
    if (route.path === '/trends' || route.path === '/advanced') setTimeout(resizeVisibleCharts, 0);
    updateOverview();
    window.scrollTo(0, 0);
  }

  function resizeVisibleCharts() {
    if (!window.Chart || typeof Chart.getChart !== 'function') return;
    document.querySelectorAll('.fp-page:not([hidden]) canvas').forEach(canvas => {
      const instance = Chart.getChart(canvas); if (instance) instance.resize();
    });
  }

  function updateOverview() {
    const root = $('fp-stats');
    if (!root || typeof S === 'undefined' || typeof META === 'undefined' || !Array.isArray(S)) return;
    const bounds = typeof range === 'function' ? range() : [];
    const rows = S.filter(row => row && (bounds.length < 2 || row.y >= bounds[0] && row.y <= bounds[1]));
    const count = key => rows.reduce((sum, row) => sum + (Number.isFinite(Number(row[key])) ? Number(row[key]) : 0), 0);
    const indexRows = rows.filter(row => row.h != null && Number.isFinite(Number(row.h)));
    const peak = indexRows.length ? indexRows.reduce((best, row) => Number(row.h) > Number(best.h) ? row : best) : null;
    const assessed = rows.filter(row => row.z != null && Number.isFinite(Number(row.z)));
    const unusual = assessed.filter(row => Math.abs(Number(row.z)) >= 2).length;
    const last = Array.isArray(META.months) && META.months.length ? META.months[META.months.length - 1] : 'Unavailable';
    const values = [
      ['Observed detections', Math.round(count('mod') + count('vii')).toLocaleString(), 'Satellite observations from both sensor families; not a count of unique fires.'],
      ['Highest activity month', peak ? peak.m : 'Not available', 'Highest MODIS-equivalent activity index in the selected years.'],
      ['Historical comparison', assessed.length ? `${unusual} unusual` : 'Not assessed', assessed.length ? `of ${assessed.length} months with a score; unusual means atypical versus history, not dangerous.` : 'No score is available for this range.'],
      ['Latest dataset month', last, 'Latest month represented in the processed dataset; this is not a live update time.']
    ];
    root.replaceChildren(...values.map(([label, value, note]) => {
      const item = document.createElement('article'); item.className = 'fp-stat';
      const title = document.createElement('span'); title.textContent = label;
      const strong = document.createElement('strong'); strong.textContent = value;
      const detail = document.createElement('small'); detail.textContent = note;
      item.append(title, strong, detail); return item;
    }));
    const text = $('fp-activity-note');
    if (text) text.textContent = assessed.length
      ? `${unusual} of ${assessed.length} assessed months are unusual compared with historical values. This describes satellite detections, not confirmed fires or fire danger.`
      : 'Historical comparison is not available for this selection or period. A hotspot is a satellite-detected thermal signal, not necessarily a wildfire.';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build, { once: true });
  else build();
})();
