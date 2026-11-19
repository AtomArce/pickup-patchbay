import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  COLOURS, displayColour, rigidGroup, hingeGroups, hinges,
  failedParts, reportSummary, jobLabel, parseQuery,
} from "./viewer-core.mjs";

const manifest = JSON.parse(
  readFileSync(new URL("../../jobs/chain-chomp/parts.manifest.json", import.meta.url), "utf8"));

const hs = hinges(manifest);
assert.equal(hs.length, 1);
const h = hs[0];
assert.equal(h.name, "jaw_hinge");
assert.deepEqual(h.moving, ["jaw_lower", "mouth_floor", "teeth_lower"]);
assert.deepEqual(h.range, [0, 40]);
assert.deepEqual(h.origin, [0, 0, 0]);
assert.deepEqual(h.direction, [0, 1, 0]);
const g = hingeGroups(manifest.mates.find((m) => m.name === "jaw_hinge"), manifest.mates);
for (const p of ["body_upper", "hinge_pin_left", "hinge_pin_right", "mouth_roof", "teeth_upper", "eye_left", "pupil_left"]) assert.ok(g.still.includes(p), p);
assert.ok(!g.still.includes("jaw_lower"));

// colours
assert.equal(displayColour("black"), 0x2a2a2e);
assert.equal(displayColour("White"), 0xf2f2ee);
assert.equal(displayColour("grey"), COLOURS.grey);
assert.equal(displayColour("brown"), 0x8b5a2b);
assert.equal(displayColour("red"), 0x9e2228);
assert.equal(displayColour("magenta"), 0x6aa3d8);
assert.equal(displayColour(undefined), 0x6aa3d8);

// failedParts
const rep = { check: "fit", passed: false, results: [
  { part: "a", rule: "wall.min", passed: true, value: 1.2, limit: 1.0, unit: "mm", note: "" },
  { part: "b", rule: "wall.min", passed: false, value: 0.4, limit: 0.8, unit: "mm", note: "" },
] };
const fp = failedParts([rep]);
assert.deepEqual([...fp.keys()], ["b"]);
assert.deepEqual(fp.get("b"), ["wall.min 0.4/0.8 mm"]);
assert.deepEqual(reportSummary(rep), { check: "fit", passed: false, total: 2, failed: 1 });

// jobLabel / parseQuery
assert.equal(jobLabel({ job: "chain-chomp", parts: 14, next: "S3" }), "chain-chomp — 14 parts, next S3");
assert.deepEqual(parseQuery("?job=chain-chomp"), { job: "chain-chomp" });
assert.deepEqual(parseQuery(""), { job: null });

// synthetic: transitive fixed chain, hinge without range, link ignored
const syn = { mates: [
  { name: "h", type: "hinge", a: "A", b: "B", axis_origin: [0, 0, 0], axis_direction: [0, 0, 2] },
  { name: "f1", type: "fixed", a: "B", b: "C" },
  { name: "f2", type: "fixed", a: "D", b: "C" },
  { name: "f3", type: "fixed", a: "D", b: "E" },
  { name: "l", type: "link", a: "E", b: "F" },
  { name: "f4", type: "fixed", a: "A", b: "G" },
] };
assert.deepEqual([...rigidGroup("B", syn.mates)].sort(), ["B", "C", "D", "E"]);
const sh = hinges(syn)[0];
assert.deepEqual(sh.moving, ["B", "C", "D", "E"]);
assert.deepEqual(hingeGroups(syn.mates[0], syn.mates).still, ["A", "G"]);
assert.deepEqual(sh.range, [0, 0]);
assert.deepEqual(sh.direction, [0, 0, 1]);

console.log("viewer-core tests passed");
