// Run with: node --experimental-strip-types --test src/textarea.test.ts (the backend tests run it too).
import assert from "node:assert/strict";
import { test } from "node:test";
import { findPassage } from "./textarea.ts";

const script = "Saddam ran Iraq for decades.\nHe hid near Tikrit,\nin a hole. Soldiers came.";

test("finds an exact passage", () => {
  const hit = findPassage(script, "He hid near Tikrit");
  assert.deepEqual(hit, { start: 29, end: 47 });
  assert.equal(script.slice(hit!.start, hit!.end), "He hid near Tikrit");
});

test("matches across a line break quoted as a space", () => {
  const hit = findPassage(script, "Tikrit, in a hole.");
  assert.ok(hit);
  assert.equal(script.slice(hit.start, hit.end), "Tikrit,\nin a hole.");
});

test("treats regex characters literally and ignores outer spaces", () => {
  assert.ok(findPassage("Was it (really) him? Yes.", "  (really) him?  "));
  assert.equal(findPassage("Was it really him?", "(really)"), null);
});

test("returns null when the text is gone", () => {
  assert.equal(findPassage(script, "Baghdad fell"), null);
  assert.equal(findPassage(script, "   "), null);
});
