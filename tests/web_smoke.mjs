// Headless smoke test of web/index.html against the REAL local server (jsdom, Leaflet/Chart.js stubbed).
// Not a visual test. Usage:  npm i jsdom   then   node tests/web_smoke.mjs http://127.0.0.1:8000/index.html
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
ok($("cal").querySelectorAll("td.cell").length > 100, "calendar rendered with month cells (whole region)");
ok($("modeChip").textContent.includes("Whole region"), "mode chip: whole region");
ok(/SYNTHETIC/.test($("originChip").textContent) === (window.document.getElementById("demo").style.display === "block"), "origin chip agrees with banner");
ok(calls.chart >= 1, "chart drawn");
for (const m of ["mod", "vii", "comb", "z", "h"]) { $("mode").value = m; $("mode").onchange(); ok($("cal").querySelectorAll("td").length > 0 && !/NaN|undefined/.test($("cal").innerHTML), `calendar mode ${m} renders without NaN/undefined`); }
const sq = [[80, 7], [81, 7], [81, 8], [80, 8]].map(([lng, lat]) => ({ lat, lng }));
handlers["draw:created"]({ layer: { getLatLngs: () => [sq] } });
await sleep(800);
ok($("modeChip").textContent.startsWith("Exact"), "after drawing: Exact mode");
ok(/km/.test($("aoiText").textContent) && $("summary").innerHTML.includes("Highest observed hotspot activity"), "area summary rendered with km2 and wording");
ok(!/most dangerous/i.test(window.document.body.innerHTML), "no 'most dangerous' wording");
ok(calls.polygons >= 1, "server-validated boundary drawn on map");
const cell = [...$("cal").querySelectorAll("td.cell")].find((c) => c.dataset.m === "2015-02");
cell.onclick(); await sleep(600);
ok(/detections shown on the map/.test($("calNote").textContent) && calls.circles > 0, "clicking a month loads real detections as map markers");
const bow = [[0, 0], [1, 1], [1, 0], [0, 1]].map(([lng, lat]) => ({ lat, lng }));
handlers["draw:created"]({ layer: { getLatLngs: () => [bow] } }); await sleep(500);
ok(/crosses itself/.test($("aoiErr").textContent) && $("modeChip").textContent.includes("Whole region"), "invalid shape: readable error and fallback to whole region");
$("y0").value = "2018"; $("y1").value = "2020"; handlers["draw:created"]({ layer: { getLatLngs: () => [sq] } }); await sleep(700);
ok($("cal").querySelectorAll("tr").length === 4, "date range 2018-2020 gives 3 year rows");
$("pointMode").onclick(); handlers["click"]({ latlng: { lat: 7.5, lng: 80.5 } }); await sleep(700);
ok(/point/i.test($("aoiText").textContent), "point selection: " + $("aoiText").textContent);
$("reset").onclick(); await sleep(200);
ok($("modeChip").textContent.includes("Whole region"), "clear returns to whole region");

// ---- Stage 5: Sensor Intelligence section
const clean = (id) => !/NaN|undefined|Infinity/.test($(id).innerHTML);
await sleep(800);
ok($("scBody").style.display === "block" && $("sensorSec") !== null, "sensor section visible (whole region)");
ok(["scA", "scB", "scC", "scD", "scE", "scE2"].every((id) => calls.cfg[id]), "all six sensor charts were created");
ok($("scBt").querySelectorAll("tr").length === 13 && ["scBt", "scDt", "scEt", "scF", "scNotes", "scMiss", "scCt"].every(clean), "sensor tables render 12 calendar months and no NaN/undefined");
ok($("scG").innerHTML.includes("Documented start") && clean("scG"), "platform timeline card renders documented vs detected months");
ok($("attribution").textContent.includes("NASA does not endorse") && $("attribution").textContent.includes("as is"), "NASA attribution, disclaimer and non-endorsement are on the page");
ok(/SYNTHETIC/.test($("scOrigin").textContent) === (window.document.getElementById("demo").style.display === "block"), "sensor provenance chip agrees with banner");
ok(/Index calibration: (AREA|REGION)/.test($("scCal").textContent), "calibration source chip: " + $("scCal").textContent);
ok(calls.cfg.scA.data.datasets.some((d) => /Harmonised index/.test(d.label)) && calls.cfg.scA.data.datasets.some((d) => /Raw combined/.test(d.label)), "chart A labels harmonised index and raw combined");
ok(calls.cfg.scB.options.scales.y.title.text.includes("ratio") && calls.cfg.scC.options.scales.x.title.text === "Month", "axis titles present");
handlers["draw:created"]({ layer: { getLatLngs: () => [sq] } }); await sleep(900);
ok(/AREA|REGION/.test($("scCal").textContent) && $("scNotes").innerHTML.includes("<li>"), "sensor panel updates after drawing an area");
ok($("scG").innerHTML.includes("NRT to standard-processing join"), "NRT/SP join panel renders under the platform timeline");
ok(!$("baseline").disabled && $("baseNote").textContent.includes("all other years"), "baseline selector enabled with the API; note names the default baseline");
$("baseline").value = "past_only"; $("baseline").onchange(); await sleep(900);
ok($("baseNote").textContent.includes("earlier years only") && !/undefined|NaN/.test($("scG").textContent), "past-only baseline reaches the API and is named on the page");
$("baseline").value = "all_other_years"; $("baseline").onchange(); await sleep(900);
const before = $("scSel").textContent;
for (const v of ["TERRA", "NOAA20", "NOAA21"]) { const c = [...window.document.querySelectorAll(".pl")].find((x) => x.value === v); c.checked = false; }
[...window.document.querySelectorAll(".pl")][0].onchange(); await sleep(900);
ok(before.startsWith("All available") && $("scSel").textContent === "MODIS Aqua vs VIIRS S-NPP", "platform subset updates the module: " + $("scSel").textContent);
ok(/subset/.test($("scCal").title + $("scNotes").innerHTML) || $("scNotes").innerHTML.includes("platform subset"), "subset note shown");
[...window.document.querySelectorAll(".pl")].forEach((c) => { c.checked = c.value !== "AQUA" && c.value !== "TERRA"; }); [...window.document.querySelectorAll(".pl")][0].onchange(); await sleep(400);
ok(/at least one MODIS/.test($("scErr").textContent), "no MODIS platform ticked: readable error, no request");
$("plAll").onclick(); await sleep(900);
ok($("scSel").textContent.startsWith("All available") && $("scErr").textContent === "", "All platforms restores the default");
$("y0").value = "2016"; $("y1").value = "2018"; $("y0").onchange(); await sleep(1000);
ok(/2016-01 to 2018-12/.test($("scPeriod").textContent), "date range drives the sensor module: " + $("scPeriod").textContent.slice(0, 40));
$("scEy").value = $("scEy").options[0].value; $("scEy").onchange(); ok(calls.cfg.scE !== undefined && clean("scEt"), "held-out year selector works");
$("scDmode").value = "p"; $("scDmode").onchange(); ok(calls.cfg.scD.options.scales.y.title.text.includes("%"), "contribution percent view");
$("reset").onclick(); await sleep(800);
ok($("scBody").style.display === "block", "sensor module follows 'clear selection'");
const csv = (() => { let t = ""; window.URL.createObjectURL = (b) => { t = b; return "blob:x"; }; window.HTMLAnchorElement.prototype.click = function () {}; $("dlCsv").onclick(); return t; })();
ok(csv && csv.size > 100, "monthly CSV generated");
console.log(fails ? `${fails} FAILURE(S)` : "ALL SMOKE CHECKS PASSED"); window.close(); process.exit(fails ? 1 : 0);
