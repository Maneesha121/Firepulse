# FirePulse multi-page dashboard

`python serve.py` now serves six application routes: `/overview`, `/map`, `/calendar`, `/trends`, `/advanced`, and `/about`. The navigation switches page views with browser history support; each route is also directly loadable and can be bookmarked. All views reuse existing dashboard components and calculations. Advanced sensor-intelligence and quality-analysis panels remain available in the Advanced Analytics route, while source and method material is grouped on About & Methodology.

The browser organizer is a progressive UI layer; it moves the existing DOM elements and preserves their IDs and event listeners. Scientific calculations, data APIs and pipeline processing are unchanged by this navigation work. Route rendering requires the Python server so it can serve the page shell and enhancement assets.

Run `python -m pytest -q tests` and `python serve.py`, then check each route directly and test the date filters, map selection, calendar month markers, downloads, and advanced analysis panels.
