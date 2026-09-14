import assert from "node:assert/strict";
import test from "node:test";

import {
  dependencyPreparationView,
  shouldRenderDependencyPreparation,
} from "../../autodrive_console/web/acceptance_preparation.js";

test("dependency preparation stays hidden when the frozen plan has no dependency orchestration", () => {
  assert.equal(
    shouldRenderDependencyPreparation({ execution_preflight: { dependency_plan_enabled: false } }),
    false,
  );
});

test("dependency preparation keeps frozen stage order and labels the live node state", () => {
  assert.deepEqual(
    dependencyPreparationView({
      execution_preflight: { dependency_plan_enabled: true },
      execution_preflight_status: {
        dependency_progress: {
          stages: [{
            index: 1,
            state: "waiting_stable",
            nodes: [{ name: "MODULES:209-lightning", status: "STARTING" }],
          }],
        },
      },
    }),
    {
      visible: true,
      stages: [{
        index: 1,
        state: "waiting_stable",
        stateLabel: "等待稳定 RUNNING",
        nodes: [{ name: "MODULES:209-lightning", status: "STARTING" }],
      }],
    },
  );
});
