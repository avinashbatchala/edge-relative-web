import { test } from "node:test";
import assert from "node:assert/strict";
import { numeric, replayPoints, fmt } from "./format.ts";
test("missing and nonfinite indicators do not become zeros", () => {
  assert.equal(numeric(null), null);
  assert.equal(numeric(NaN), null);
  assert.equal(fmt(undefined), "—");
  assert.equal(fmt(0), "0.00");
});
test("replay exposes only the selected prefix", () => {
  assert.deepEqual(replayPoints([1, 2, 3, 4], 2), [1, 2]);
  assert.deepEqual(replayPoints([1, 2], -1), []);
});
