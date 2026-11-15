// Headless check of the quality section (jsdom, Leaflet/Chart.js stubbed) against the REAL local server. Not a visual test.
// Usage:  npm i jsdom ; python serve.py --demo ; node tests/web_quality_smoke.mjs http://127.0.0.1:8000/index.html
import { JSDOM } from "jsdom";
const url = process.argv[2] || "http://127.0.0.1:8000/index.html";
const handlers = {}, calls = { chart: 0, polygons: 0, circles: 0, cfg: {} };
const chain = () => new Proxy(function () {}, { get: (_, k) => (k === "addTo" ? () => chain() : () => chain()), apply: () => chain() });
const html = await (await fetch(url)).text();
const dom = new JSDOM(html, {
  url, runScripts: "dangerously", pretendToBeVisual: true,
  beforeParse(w) {
    w.fetch = (u, o) => fetch(new URL(u, url), o);
    const grp = () => ({ addTo() { return this; }, clearLayers() {}, addLayer() {}, eachLayer() {} });
    w.L = {
      map: () => ({ setView() { return this; }, on(ev, fn) { handlers[ev] = fn; }, addControl() {}, getContainer: () => ({ style: {} }) }),
      tileLayer: () => chain(), rectangle: () => chain(), FeatureGroup: function () { return grp(); }, layerGroup: () => grp(),
      Control: { Draw: function () {} }, Draw: { Event: { CREATED: "draw:created", EDITED: "draw:edited", DELETED: "draw:deleted" } },
      polygon: () => { calls.polygons++; return { addTo() { return this; } }; },
      circleMarker: () => { calls.circles++; return { bindPopup() { return this; }, addTo() { return this; } }; },
    };
    w.Chart = function (el, cfg) { calls.chart++; calls.lastChart = cfg; calls.cfg[el && el.id] = cfg; this.destroy = () => {}; };
  },
});
const { window } = dom, $ = (id) => window.document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
window.addEventListener("error", (e) => { console.log("PAGE ERROR", e.message); fails++; });
await sleep(1500);
window.eval("qVisible=true;loadQuality()");
await sleep(3500);
ok($("qBody").style.display === "grid", "quality section rendered");
ok($("qSteps").querySelectorAll("tr").length > 10 && /removed: invalid/.test($("qSteps").textContent), "removal steps table with kinds");
ok($("qFlags").querySelectorAll("tr").length > 15, "flag table");
ok($("qProfiles").querySelectorAll("tr").length === 8, "7 profiles + header");
ok($("qDelta").querySelectorAll("tr").length > 20 && !/NaN|undefined/.test($("qDelta").innerHTML), "delta calendar");
ok(!/NaN|undefined/.test($("qSteps").innerHTML + $("qFlags").innerHTML + $("qProfiles").innerHTML + $("qAnom").innerHTML + $("qPlat").innerHTML), "no NaN/undefined in tables");
ok(calls.cfg.qA && calls.cfg.qB, "charts A and B created");
ok(/SYNTHETIC/.test($("qOrigin").textContent), "origin chip");
const sq = [[80, 7], [81, 7], [81, 8], [80, 8]].map(([lng, lat]) => ({ lat, lng }));
handlers["draw:created"]({ layer: { getLatLngs: () => [sq] } });
await sleep(3500);
ok(/valid records/.test($("qSel").textContent) && !/whole/.test($("qSel").textContent), "quality follows drawn area: " + $("qSel").textContent);
console.log(fails ? fails + " FAILURE(S)" : "ALL OK");
process.exit(0);
