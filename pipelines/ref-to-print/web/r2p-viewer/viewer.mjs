import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { displayColour, hinges, failedParts, reportSummary, jobLabel, parseQuery } from "./viewer-core.mjs";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1); // Z up, millimetres

const $ = (id) => document.getElementById(id);
const host = $("canvas-host");
const statusEl = $("status");
function setStatus(msg, isErr = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("err", isErr);
  if (isErr) console.error(msg);
}

// ---- scene ----
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
host.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 1, 5000);
camera.position.set(250, -350, 250);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 1.0));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(200, -300, 400);
scene.add(sun);
const axes = new THREE.AxesHelper(60);
axes.visible = false;
scene.add(axes);

function setBackground() {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  scene.background = new THREE.Color(dark ? 0x1a1c21 : 0xeceef2);
}
setBackground();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", setBackground);

function resize() {
  const w = host.clientWidth || window.innerWidth, h = host.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

(function loop() {
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, camera);
})();

// ---- state ----
let jobs = [];
let loadToken = 0;
let st = null; // per-job state
const jobGroup = new THREE.Group();
scene.add(jobGroup);
let bedGroup = null;
let selectedName = null;
const RED = new THREE.Color(0xd03a3a);

function clearJob() {
  for (const o of [...jobGroup.children]) jobGroup.remove(o);
  if (st) for (const p of st.parts.values()) { p.mesh.geometry.dispose(); p.mesh.material.dispose(); }
  if (bedGroup) { scene.remove(bedGroup); bedGroup = null; }
  st = null; selectedName = null;
  $("parts").innerHTML = ""; $("hinges").innerHTML = '<span class="muted">none</span>';
  $("checks").innerHTML = '<li class="muted">none</li>';
  $("selected").textContent = "Click a part to select it.";
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function loadJob(name) {
  const token = ++loadToken;
  clearJob();
  const entry = jobs.find((j) => j.job === name);
  if (!entry) { setStatus(`Unknown job: ${name}`, true); return; }
  try {
    setStatus(`Loading ${name} manifest…`);
    const base = `/jobs/${encodeURIComponent(name)}`;
    const manifest = await getJson(`${base}/parts.manifest.json`);
    const errors = [];
    const [printer, reports] = await Promise.all([
      entry.printer ? getJson(`/printer/${encodeURIComponent(entry.printer)}.json`).catch((e) => { errors.push(e.message); return null; }) : null,
      Promise.all((entry.reports || []).map((p) => getJson(`${base}/${p}`).catch((e) => { errors.push(e.message); return null; }))),
    ]);
    if (token !== loadToken) return;
    const goodReports = reports.filter(Boolean);
    const failed = failedParts(goodReports);

    const loader = new STLLoader();
    let done = 0;
    const total = manifest.parts.length;
    setStatus(`Loading STLs 0/${total}…`);
    const parts = new Map();
    await Promise.all(manifest.parts.map(async (p) => {
      try {
        const geom = await loader.loadAsync(`${base}/${p.stl}`);
        if (!geom.getAttribute("normal")) geom.computeVertexNormals();
        const mat = new THREE.MeshStandardMaterial({ color: displayColour(p.colour), roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geom, mat);
        mesh.userData.part = p.name;
        parts.set(p.name, { info: p, mesh, visible: true });
      } catch (e) {
        errors.push(`${p.name}: ${e.message || e}`);
      }
      done++;
      if (token === loadToken) setStatus(`Loading STLs ${done}/${total}…`);
    }));
    if (token !== loadToken) return;

    st = { name, manifest, printer, reports: goodReports, failed, parts, pivots: [] };
    buildHinges(manifest);
    for (const p of parts.values()) if (!p.mesh.parent) jobGroup.add(p.mesh);
    for (const p of parts.values()) applyMaterial(p);
    buildPartsList();
    buildChecks();
    buildBed();
    resetView();
    setStatus(errors.length ? `Loaded ${parts.size}/${total} parts; problems: ${errors.join("; ")}` : `Loaded ${parts.size} parts.`, errors.length > 0);
  } catch (e) {
    if (token === loadToken) setStatus(`Failed to load ${name}: ${e.message || e}`, true);
  }
}

// ---- hinges ----
function buildHinges(manifest) {
  const box = $("hinges");
  const hs = hinges(manifest);
  if (!hs.length) return;
  box.innerHTML = "";
  const used = new Set();
  for (const h of hs) {
    const pivot = new THREE.Group();
    pivot.position.fromArray(h.origin);
    jobGroup.add(pivot);
    for (const pn of h.moving) {
      const p = st.parts.get(pn);
      if (!p || used.has(pn)) continue; // a part moves with only the first hinge that claims it
      used.add(pn);
      p.mesh.position.set(-h.origin[0], -h.origin[1], -h.origin[2]); // so rotation is about the axis origin
      pivot.add(p.mesh);
    }
    const axis = new THREE.Vector3().fromArray(h.direction);
    const wrap = document.createElement("div");
    wrap.className = "hinge";
    const label = document.createElement("label");
    const text = document.createElement("span");
    const slider = document.createElement("input");
    slider.type = "range"; slider.min = h.range[0]; slider.max = h.range[1]; slider.step = 0.5; slider.value = h.range[0];
    slider.disabled = h.range[0] === h.range[1];
    const update = () => {
      const deg = Number(slider.value);
      pivot.quaternion.setFromAxisAngle(axis, THREE.MathUtils.degToRad(deg));
      text.textContent = `${h.name} ${h.range[0]}°…${h.range[1]}° = ${deg.toFixed(1)}°`;
    };
    slider.addEventListener("input", update);
    label.append(text, slider);
    wrap.append(label);
    box.append(wrap);
    update();
  }
}

// ---- parts ----
function applyMaterial(p) {
  const bad = st.failed.has(p.info.name);
  const m = p.mesh.material;
  m.emissive = bad ? RED : new THREE.Color(0x000000);
  m.emissiveIntensity = bad ? 0.45 : 0;
  m.wireframe = $("t-wire").checked;
  if (p.info.name === selectedName) { m.emissive = new THREE.Color(0x2f6fdb); m.emissiveIntensity = 0.5; }
  p.mesh.visible = p.visible;
}

function buildPartsList() {
  const ul = $("parts");
  for (const [name, p] of st.parts) {
    const li = document.createElement("li");
    li.dataset.part = name;
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true;
    cb.addEventListener("change", () => { p.visible = cb.checked; applyMaterial(p); });
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = "#" + displayColour(p.info.colour).toString(16).padStart(6, "0");
    const nm = document.createElement("span");
    nm.className = "name"; nm.textContent = name;
    nm.addEventListener("click", () => select(name));
    li.append(cb, sw, nm);
    if (st.failed.has(name)) {
      li.classList.add("fail");
      li.title = st.failed.get(name).join("\n");
    }
    ul.append(li);
  }
}

$("show-all").addEventListener("click", (ev) => {
  ev.preventDefault();
  if (!st) return;
  for (const p of st.parts.values()) { p.visible = true; applyMaterial(p); }
  for (const cb of $("parts").querySelectorAll("input")) cb.checked = true;
});

function select(name) {
  const prev = selectedName && st.parts.get(selectedName);
  selectedName = name;
  if (prev) applyMaterial(prev);
  const p = name && st.parts.get(name);
  for (const li of $("parts").children) li.classList.toggle("sel", li.dataset.part === name);
  if (!p) { $("selected").textContent = "Click a part to select it."; return; }
  applyMaterial(p);
  const b = p.info.bbox_mm;
  const size = b ? b.max.map((v, i) => (v - b.min[i]).toFixed(1)).join(" × ") : "?";
  const vol = p.info.volume_mm3 != null ? `${Math.round(p.info.volume_mm3)} mm³` : "?";
  const fails = st.failed.get(name);
  $("selected").textContent = `${name}: ${size} mm, volume ${vol}` + (fails ? `\nFails: ${fails.join("; ")}` : "");
  $("selected").style.whiteSpace = "pre-wrap";
}

function buildChecks() {
  const ul = $("checks");
  if (!st.reports.length) return;
  ul.innerHTML = "";
  for (const rep of st.reports) {
    const s = reportSummary(rep);
    const li = document.createElement("li");
    li.innerHTML = `<span class="${s.passed ? "pass" : "fail"}">${s.passed ? "PASS" : "FAIL"}</span> `;
    li.append(`${s.check}` + (s.failed ? ` (${s.failed} failed of ${s.total})` : ` (${s.total})`));
    ul.append(li);
  }
}

// ---- bed ----
function buildBed() {
  const vol = st.printer && st.printer.build_volume_mm;
  if (!vol || !st.parts.size) return;
  const box = new THREE.Box3();
  for (const p of st.parts.values()) {
    const b = p.info.bbox_mm;
    if (!b) continue;
    box.expandByPoint(new THREE.Vector3(...b.min));
    box.expandByPoint(new THREE.Vector3(...b.max));
  }
  if (box.isEmpty()) return;
  const cx = (box.min.x + box.max.x) / 2, cy = (box.min.y + box.max.y) / 2, z0 = box.min.z;
  bedGroup = new THREE.Group();
  const [bx, by, bz] = vol;
  const rect = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints([[-bx / 2, -by / 2], [bx / 2, -by / 2], [bx / 2, by / 2], [-bx / 2, by / 2]].map(([x, y]) => new THREE.Vector3(x, y, 0))),
    new THREE.LineBasicMaterial({ color: 0x2f6fdb }));
  const wire = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(bx, by, bz).translate(0, 0, bz / 2)),
    new THREE.LineBasicMaterial({ color: 0x8a94a6, transparent: true, opacity: 0.5 }));
  bedGroup.add(rect, wire);
  bedGroup.position.set(cx, cy, z0);
  bedGroup.visible = $("t-bed").checked;
  scene.add(bedGroup);
}

// ---- view ----
function resetView() {
  const box = new THREE.Box3();
  jobGroup.updateMatrixWorld(true);
  for (const p of st ? st.parts.values() : []) if (p.visible) box.union(new THREE.Box3().setFromObject(p.mesh));
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1);
  const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.1;
  camera.near = Math.max(dist / 1000, 0.1);
  camera.far = dist * 20 + 2000;
  camera.updateProjectionMatrix();
  camera.position.copy(c).add(new THREE.Vector3(0.6, -0.8, 0.6).normalize().multiplyScalar(dist));
  controls.target.copy(c);
  controls.update();
}
$("reset-view").addEventListener("click", resetView);
$("t-bed").addEventListener("change", (e) => { if (bedGroup) bedGroup.visible = e.target.checked; });
$("t-axes").addEventListener("change", (e) => { axes.visible = e.target.checked; });
$("t-wire").addEventListener("change", () => { if (st) for (const p of st.parts.values()) applyMaterial(p); });
$("screenshot").addEventListener("click", () => {
  renderer.render(scene, camera);
  const a = document.createElement("a");
  a.href = renderer.domElement.toDataURL("image/png");
  a.download = `${st ? st.name : "r2p"}.png`;
  a.click();
});
$("panel-toggle").addEventListener("click", () => {
  const c = $("panel").classList.toggle("collapsed");
  $("panel-toggle").setAttribute("aria-expanded", String(!c));
});
if (window.innerWidth <= 700) $("panel").classList.add("collapsed");

// ---- picking ----
const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
function pick(ev) {
  if (!st) return null;
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const meshes = [...st.parts.values()].filter((p) => p.visible).map((p) => p.mesh);
  const hit = ray.intersectObjects(meshes, false)[0];
  return hit ? hit.object.userData.part : null;
}
const hover = $("hover");
renderer.domElement.addEventListener("pointermove", (ev) => {
  const name = pick(ev);
  hover.hidden = !name;
  if (name) { hover.textContent = name; hover.style.left = ev.clientX + 12 + "px"; hover.style.top = ev.clientY + 12 + "px"; }
});
renderer.domElement.addEventListener("pointerleave", () => { hover.hidden = true; });
let down = null;
renderer.domElement.addEventListener("pointerdown", (ev) => { down = [ev.clientX, ev.clientY]; });
renderer.domElement.addEventListener("pointerup", (ev) => {
  if (!down || Math.hypot(ev.clientX - down[0], ev.clientY - down[1]) > 4) return; // a drag, not a click
  select(pick(ev));
});

// ---- boot ----
async function boot() {
  try {
    const data = await getJson("/api/jobs");
    jobs = data.jobs || [];
    const sel = $("job");
    for (const j of jobs) {
      const o = document.createElement("option");
      o.value = j.job; o.textContent = jobLabel(j);
      sel.append(o);
    }
    if (!jobs.length) { setStatus("No jobs with a parts.manifest.json found.", true); return; }
    const want = parseQuery(location.search).job;
    sel.value = jobs.some((j) => j.job === want) ? want : jobs[0].job;
    sel.addEventListener("change", () => {
      const u = new URL(location.href);
      u.searchParams.set("job", sel.value);
      history.replaceState(null, "", u);
      loadJob(sel.value);
    });
    loadJob(sel.value);
  } catch (e) {
    setStatus(`Could not load /api/jobs: ${e.message || e}`, true);
  }
}
boot();
