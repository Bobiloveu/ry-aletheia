import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = new URL("../../../autodrive_console/web/deployment.html", import.meta.url);
const script = new URL("../../../autodrive_console/web/deployment.js", import.meta.url);

test("map import picker accepts the localization index beside YAML, PGM and PCD", () => {
  const markup = readFileSync(html, "utf8");
  const source = readFileSync(script, "utf8");

  assert.match(
    markup,
    /id="mapFolder"[^>]*accept="[^"]*\.txt[^"]*"/,
    "the browser must let operators select index.txt required by localization exports",
  );
  assert.match(
    source,
    /files\.forEach\(\(file\) => payload\.append\("files", file,/,
    "the selected index must travel with the same controlled upload request",
  );
});
