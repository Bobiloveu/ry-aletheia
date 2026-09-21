import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = new URL("../../../autodrive_console/web/deployment.html", import.meta.url);
const script = new URL("../../../autodrive_console/web/deployment.js", import.meta.url);

test("map import picker accepts optional compatibility index beside YAML, PGM and PCD", () => {
  const markup = readFileSync(html, "utf8");
  const source = readFileSync(script, "utf8");

  assert.match(
    markup,
    /id="mapFolder"[^>]*accept="[^"]*\.txt[^"]*"/,
    "the browser must let operators select an optional compatibility index",
  );
  assert.match(
    source,
    /files\.forEach\(\(file\) => payload\.append\("files", file,/,
    "the selected index must travel with the same controlled upload request",
  );
  assert.match(
    source,
    /yamlCount !== 1 \|\| pgmCount < 1/,
    "the import action must stay locked until one YAML and a PGM are selected",
  );
  assert.match(
    source,
    /index\.txt.*可选|可选.*index\.txt/s,
    "index.txt must remain optional compatibility metadata",
  );
});
