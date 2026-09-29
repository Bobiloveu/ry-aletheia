import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const repoRoot = new URL("../..", import.meta.url);
const read = (path) => readFileSync(new URL(path, repoRoot), "utf8");

test("Vue entry pages provide a stable, styled first paint before modules mount", () => {
  for (const pagePath of [
    "frontend/dashboard.html",
    "frontend/index.html",
    "frontend/runtime-settings.html",
    "frontend/live-observation.html",
  ]) {
    const page = read(pagePath);
    assert.match(page, /<style data-shell-boot>/, `${pagePath} needs critical boot styles`);
    assert.match(page, /data-page-ready="false"/, `${pagePath} should start behind the boot guard`);
  }

  assert.match(read("frontend/src/pageBoot.js"), /app\.dataset\.pageReady = "true"/);

  const livePage = read("frontend/live-observation.html");
  assert.match(livePage, /\.mark svg\s*\{[^}]*width:\s*34px[^}]*height:\s*34px/s);
  assert.match(livePage, /#app\[data-page-ready="false"\]\s*\{[^}]*visibility:\s*hidden/s);
});

test("desktop shell applies one accessible transition to internal menu navigation", () => {
  const shell = read("autodrive_console/web/app_shell.js");
  const stylesheet = read("autodrive_console/web/app_shell.css");

  assert.match(shell, /const installNavigationTransition = \(\) =>/);
  assert.match(shell, /document\.addEventListener\('click'/);
  assert.match(shell, /event\.target\.closest\('aside nav a\[href\]'\)/,
    "only sidebar menu links may enter the page-transition flow");
  assert.doesNotMatch(shell, /event\.target\.closest\('a\[href\]'\)/,
    "downloads and in-page action links must remain outside the transition flow");
  assert.match(shell, /dataset\.navigationState/, "leaving state must be visible to CSS");
  assert.match(shell, /prefers-reduced-motion/);
  assert.match(shell, /window\.location\.assign/);
  assert.match(stylesheet, /@media \(prefers-reduced-motion:\s*no-preference\)\s*\{\s*@view-transition\s*\{\s*navigation:\s*auto;/s);
  assert.match(stylesheet, /html\[data-navigation-state="leaving"\]/);
  assert.match(stylesheet, /@media \(prefers-reduced-motion:\s*reduce\)/);
});
