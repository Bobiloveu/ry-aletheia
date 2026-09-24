import assert from "node:assert/strict";
import test from "node:test";

import {
  SESSION_STORAGE_KEY,
  clearDeploymentSession,
  clampDeploymentStage,
  readDeploymentSession,
  writeDeploymentSession,
} from "../../autodrive_console/web/deployment/session-state.js";

function storage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
    raw(key) {
      return values.get(key);
    },
  };
}

test("deployment session restores only view pointers and safe task drafts", () => {
  const store = storage();

  writeDeploymentSession(store, {
    projectId: "site-1",
    mapId: "map-2",
    viewedDeploymentStage: "localization",
    deploymentTaskDraft: { mapSource: "import", mapLabel: "电梯大厅" },
  });

  assert.deepEqual(readDeploymentSession(store), {
    version: 1,
    projectId: "site-1",
    mapId: "map-2",
    viewedDeploymentStage: "localization",
    deploymentTaskDraft: { mapSource: "import", mapLabel: "电梯大厅" },
  });
  assert.doesNotMatch(store.raw(SESSION_STORAGE_KEY), /components|routes|scene_model/);
});

test("deployment session ignores malformed or incomplete persisted values", () => {
  const store = storage();
  store.setItem(SESSION_STORAGE_KEY, JSON.stringify({ projectId: "site-1", components: [] }));

  assert.equal(readDeploymentSession(store), null);

  store.setItem(SESSION_STORAGE_KEY, "not-json");
  assert.equal(readDeploymentSession(store), null);
});

test("deployment session clamps a requested stage to the server-unlocked stage", () => {
  assert.equal(clampDeploymentStage("maps", "localization"), "maps");
  assert.equal(clampDeploymentStage("localization", "maps"), "maps");
  assert.equal(clampDeploymentStage("localization", "localization"), "localization");
  assert.equal(clampDeploymentStage("maps", "unknown"), "maps");
});

test("deployment session can be cleared when the saved project no longer exists", () => {
  const store = storage();
  writeDeploymentSession(store, { projectId: "deleted", mapId: "map-1", viewedDeploymentStage: "maps" });

  clearDeploymentSession(store);

  assert.equal(readDeploymentSession(store), null);
});
