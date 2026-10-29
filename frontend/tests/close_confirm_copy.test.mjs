import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../ui/shared/components/close_confirm/close_confirm.js", import.meta.url),
  "utf8",
);

test("dirty-close confirmation names the action and offers Close / Keep editing", () => {
  assert.match(source, /"Close without saving\?"/);
  assert.match(source, /"Unsaved changes will be lost\."/);
  assert.match(source, /data-close-confirm-value="yes">Close<\/button>/);
  assert.match(source, /data-close-confirm-value="cancel">Keep editing<\/button>/);
  assert.doesNotMatch(source, /Cancel and close/);
  assert.doesNotMatch(source, />Yes<\/button>|>No<\/button>/);
});

test("cancel-changes variant says Discard instead of Yes", () => {
  assert.match(source, /"Discard changes\?"/);
  assert.match(source, /"Discard"/);
});

test("hosts that close from several places can reuse one dialog per document", () => {
  assert.match(source, /export function confirmDiscardClose\(/);
});
