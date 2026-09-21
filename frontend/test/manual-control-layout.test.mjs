import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import postcss from "postcss";

function declarationsFor(root, selector) {
  const declarations = new Map();
  root.walkRules((rule) => {
    if (rule.selector !== selector) return;
    rule.walkDecls((declaration) => declarations.set(declaration.prop, declaration.value));
  });
  return declarations;
}

test("key binding dialog contains global button dimensions within its own layout", () => {
  const file = new URL("../../autodrive_console/web/manual_control.css", import.meta.url);
  const root = postcss.parse(readFileSync(file, "utf8"), { from: file.pathname });

  const header = declarationsFor(root, ".key-binding-dialog__header");
  assert.equal(header.get("display"), "flex");

  const headerCopy = declarationsFor(root, ".key-binding-dialog__header > div");
  assert.equal(headerCopy.get("min-width"), "0");
  assert.equal(headerCopy.get("flex"), "1 1 auto");

  const close = declarationsFor(root, ".key-binding-close");
  assert.equal(close.get("width"), "auto");
  assert.equal(close.get("margin"), "0");

  const lightClose = declarationsFor(root, "body.theme-light .key-binding-close");
  assert.equal(lightClose.get("background"), "transparent");
  assert.equal(lightClose.get("color"), "var(--muted)");
});
