import assert from "node:assert/strict";
import test from "node:test";

import { synchronizeMapSourceChoice } from "../../../autodrive_console/web/deployment/map-source-choice.js";

function sourceChoices(initial = {}) {
  const choices = ["import", "mapping"].map((source) => ({
    dataset: { mapSource: source },
    checked: Boolean(initial[source]),
  }));
  return {
    choices,
    root: {
      querySelectorAll(selector) {
        assert.equal(selector, "[data-map-source]");
        return choices;
      },
    },
  };
}

test("resetting a completed map import unchecks every map source", () => {
  const { choices, root } = sourceChoices({ import: true });

  synchronizeMapSourceChoice(root, null);

  assert.deepEqual(choices.map(({ dataset, checked }) => [dataset.mapSource, checked]), [
    ["import", false],
    ["mapping", false],
  ]);
});

test("map source synchronization selects exactly the source held by the current draft", () => {
  const { choices, root } = sourceChoices({ import: true, mapping: true });

  synchronizeMapSourceChoice(root, "mapping");

  assert.deepEqual(choices.map(({ dataset, checked }) => [dataset.mapSource, checked]), [
    ["import", false],
    ["mapping", true],
  ]);
});
