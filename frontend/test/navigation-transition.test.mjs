import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const repoRoot = new URL("../..", import.meta.url);
const read = (path) => readFileSync(new URL(path, repoRoot), "utf8");
const legacyMenuPages = [
  "autodrive_console/web/index.html",
  "autodrive_console/web/deployment.html",
  "autodrive_console/web/acceptance-test.html",
  "autodrive_console/web/manual-control.html",
  "autodrive_console/web/case-library.html",
  "autodrive_console/web/reports.html",
  "autodrive_console/web/robot-logs.html",
  "autodrive_console/web/runtime-settings.html",
  "autodrive_console/web/scenario-setup.html",
  "autodrive_console/web/tool-logs.html",
  "autodrive_console/web/mapping-workbench.html",
];

test("Vue entry pages keep their chosen theme and visible shell stable before modules mount", () => {
  for (const pagePath of [
    "frontend/dashboard.html",
    "frontend/index.html",
    "frontend/runtime-settings.html",
    "frontend/live-observation.html",
  ]) {
    const page = read(pagePath);
    assert.match(page, /<style data-shell-boot>/, `${pagePath} needs critical boot styles`);
    assert.match(page, /ry-aletheia-theme/, `${pagePath} must read the saved theme before first paint`);
    assert.match(page, /html\[data-theme="light"\]/, `${pagePath} must not flash the dark canvas for light-theme operators`);
    assert.doesNotMatch(page, /visibility:\s*hidden/, `${pagePath} must never hide the whole application during navigation`);
    assert.doesNotMatch(page, /opacity:\s*0/, `${pagePath} must never fade to a blank frame`);
  }

  const livePage = read("frontend/live-observation.html");
  const liveStyleLink = '<link rel="stylesheet" href="/src/liveObservationEntry.css" />';
  assert.ok(
    livePage.indexOf(liveStyleLink) >= 0
      && livePage.indexOf(liveStyleLink) < livePage.indexOf("<body>"),
    "the live viewer must load its complete CSS before the browser can paint its static body",
  );
  const liveStyleEntry = read("frontend/src/liveObservationEntry.css");
  const liveStyleOrder = [
    "styles.css",
    "refinement.css",
    "page_views.css",
    "liveObservation.css",
    "app_shell.css",
  ];
  let previousStyleOffset = -1;
  for (const stylesheet of liveStyleOrder) {
    const styleOffset = liveStyleEntry.indexOf(stylesheet);
    assert.ok(styleOffset > previousStyleOffset, `${stylesheet} must retain the existing cascade order`);
    previousStyleOffset = styleOffset;
  }
  assert.match(livePage, /\.mark svg\s*\{[^}]*width:\s*34px[^}]*height:\s*34px/s);
  assert.match(
    livePage,
    /\.mark svg\s*\{[^}]*fill:\s*none[^}]*stroke:\s*#fff/s,
    "the desktop brand mark must not render as a solid black triangle before module CSS loads",
  );
  assert.match(
    livePage,
    /\.mobile-console-bar,\s*\.mobile-bottom-nav\s*\{[^}]*display:\s*none/s,
    "mobile-only SVG navigation must stay out of the desktop first paint",
  );
});

test("legacy menu pages apply the saved theme before loading the shared shell", () => {
  for (const pagePath of legacyMenuPages) {
    const page = read(pagePath);
    assert.match(page, /<script src="\/theme_bootstrap\.js"><\/script>/,
      `${pagePath} must select the saved theme before styles paint`);
  }
  assert.match(read("frontend/vite.config.js"), /"\/theme_bootstrap\.js"/);
  assert.match(read("autodrive_console/web/app_shell.css"), /html\[data-theme="light"\] body/);
  assert.match(read("autodrive_console/web/scenario_setup.css"), /html\[data-theme="light"\]\s+\.scenario-help/);
  assert.match(read("autodrive_console/web/tool_logs.css"), /\.diagnostic-file-row\s*\{[^}]*background:\s*var\(--surface-sunken\)/s, "tool log rows inherit the theme selected before paint");
  assert.doesNotMatch(read("autodrive_console/web/vehicle-execution-status.html"), /theme_bootstrap\.js/);
});

test("desktop shell leaves menu navigation native and never captures a reshaping page", () => {
  const shell = read("autodrive_console/web/app_shell.js");
  const stylesheet = read("autodrive_console/web/app_shell.css");

  assert.doesNotMatch(shell, /installNavigationTransition/);
  assert.doesNotMatch(shell, /navigationState/);
  assert.doesNotMatch(stylesheet, /@view-transition/);
  assert.doesNotMatch(stylesheet, /data-navigation-state/);
  assert.doesNotMatch(stylesheet, /transition:\s*opacity/);
  assert.doesNotMatch(read("frontend/src/dashboard.js"), /routeLegacyPage/);
  assert.doesNotMatch(read("frontend/src/dashboard.js"), /dashboardHost\.value(?:\?\.)?\.addEventListener\(\s*["']click["']/);
  const runtimeSettings = read("frontend/src/main.js");
  const nav = runtimeSettings.slice(runtimeSettings.indexOf("<nav>"), runtimeSettings.indexOf("</nav>") + 6);
  assert.doesNotMatch(nav, /(?:@click|v-on:click)/);
});
