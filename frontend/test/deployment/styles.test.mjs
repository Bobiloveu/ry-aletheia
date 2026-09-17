import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import postcss from "postcss";

test("deployment CSS keeps hidden panels and desktop media rules structurally valid", () => {
  const file = new URL("../../../autodrive_console/web/deployment.css", import.meta.url);
  const root = postcss.parse(readFileSync(file, "utf8"), { from: file.pathname });
  const hiddenRules = [];
  root.walkRules((rule) => {
    assert.doesNotMatch(rule.selector, /@media/, "media blocks must not become a selector");
    if (rule.selector.includes(".localization-binding-panel")) {
      rule.walkDecls("display", (declaration) => {
        if (declaration.value === "none") hiddenRules.push(rule);
      });
    }
  });
  assert.ok(hiddenRules.some((rule) => rule.selector.includes("body.deployment-no-project")));
  assert.ok(hiddenRules.some((rule) => rule.selector.includes("body:not(.deployment-no-project).deployment-no-map")));
  const desktop = root.nodes.filter((node) => node.type === "atrule" && node.name === "media");
  assert.ok(desktop.some((media) => media.nodes.some((rule) => (
    rule.type === "rule" && rule.selector === "body:has(#mapWorkspace) .page-grid"
      && rule.nodes.some((declaration) => declaration.prop === "grid-template-columns"
        && declaration.value.includes("minmax(264px, 300px)"))
  ))), "the main three-column editor must remain inside its own media block");
});
