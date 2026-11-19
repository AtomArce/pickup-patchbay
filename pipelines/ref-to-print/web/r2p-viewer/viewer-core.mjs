// Pure helpers for the r2p viewer. No three.js, no DOM: testable in Node.

export const COLOURS = {
  black: 0x2a2a2e,
  white: 0xf2f2ee,
  grey: 0x9aa0a6,
  brown: 0x8b5a2b,
  red: 0x9e2228,
};
export const FALLBACK_COLOUR = 0x6aa3d8;

export function displayColour(name) {
  const key = String(name ?? "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(COLOURS, key) ? COLOURS[key] : FALLBACK_COLOUR;
}

/** root plus every part reachable from it through fixed mates (transitively). Mirrors checks/mate_check.py. */
export function rigidGroup(root, mates) {
  const group = new Set([root]);
  const todo = [root];
  while (todo.length) {
    const cur = todo.pop();
    for (const m of mates || []) {
      if (m.type === "fixed" && (cur === m.a || cur === m.b)) {
        const other = m.a === cur ? m.b : m.a;
        if (!group.has(other)) {
          group.add(other);
          todo.push(other);
        }
      }
    }
  }
  return group;
}

/** {moving, still}: sorted arrays. moving = group of b, still = group of a. */
export function hingeGroups(mate, mates) {
  return {
    moving: [...rigidGroup(mate.b, mates)].sort(),
    still: [...rigidGroup(mate.a, mates)].sort(),
  };
}

export function hinges(manifest) {
  const mates = (manifest && manifest.mates) || [];
  return mates
    .filter((m) => m.type === "hinge")
    .map((m) => {
      const d = m.axis_direction || [0, 0, 1];
      const len = Math.hypot(d[0], d[1], d[2]) || 1;
      const r = Array.isArray(m.range_deg) && m.range_deg.length === 2 ? m.range_deg : [0, 0];
      return {
        name: m.name,
        a: m.a,
        b: m.b,
        origin: m.axis_origin ? [...m.axis_origin] : [0, 0, 0],
        direction: [d[0] / len, d[1] / len, d[2] / len],
        range: [r[0], r[1]],
        moving: hingeGroups(m, mates).moving,
      };
    });
}

function fmt(v) {
  if (typeof v !== "number") return v == null ? "" : String(v);
  return String(Math.round(v * 1000) / 1000);
}

/** Map part -> ["rule value/limit unit", ...] for failed results across reports. */
export function failedParts(reports) {
  const out = new Map();
  for (const rep of reports || []) {
    for (const r of (rep && rep.results) || []) {
      if (r.passed !== false) continue;
      const part = r.part ?? "(job)";
      const vl = r.limit == null ? fmt(r.value) : `${fmt(r.value)}/${fmt(r.limit)}`;
      const text = [r.rule, vl, r.unit].filter((s) => s !== "" && s != null).join(" ");
      if (!out.has(part)) out.set(part, []);
      out.get(part).push(text);
    }
  }
  return out;
}

export function reportSummary(report) {
  const results = (report && report.results) || [];
  const failed = results.filter((r) => r.passed === false).length;
  return { check: report && report.check, passed: !!(report && report.passed), total: results.length, failed };
}

export function jobLabel(job) {
  const next = job.next ? `next ${job.next}` : "all steps done";
  return `${job.job} — ${job.parts} parts, ${next}`;
}

export function parseQuery(search) {
  const p = new URLSearchParams(search || "");
  return { job: p.get("job") || null };
}
