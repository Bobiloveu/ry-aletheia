import assert from "node:assert/strict";
import test from "node:test";

import {
  activeAcceptancePlanSelection,
  acceptancePlanPreflightPayload,
  dependencyPreparationView,
  readyPlanReplacementNotice,
  shouldRenderPreparationRuntime,
  shouldRenderDependencyPreparation,
} from "../../autodrive_console/web/acceptance_preparation.js";

test("acceptance plan request exposes only the boolean automatic-return choice", () => {
  assert.deepEqual(
    acceptancePlanPreflightPayload({
      scenarioProfileId: "night-shift",
      dependencyPlanEnabled: true,
      automaticReturnEnabled: true,
    }),
    {
      scenario_profile_id: "night-shift",
      use_dependency_plan: true,
      use_automatic_return: true,
    },
  );
  assert.deepEqual(
    acceptancePlanPreflightPayload({ automaticReturnEnabled: false }),
    {
      scenario_profile_id: null,
      use_dependency_plan: false,
      use_automatic_return: false,
    },
  );
});

test("dependency preparation stays hidden when the frozen plan has no dependency orchestration", () => {
  assert.equal(
    shouldRenderDependencyPreparation({ execution_preflight: { dependency_plan_enabled: false } }),
    false,
  );
});

test("terminal acceptance plans do not show a persisted preparation snapshot as live work", () => {
  const plan = {
    status: "failed",
    execution_preflight: { dependency_plan_enabled: true },
    execution_preflight_status: { state: "ready", message: "正在开始第一项验收任务" },
  };
  assert.equal(shouldRenderDependencyPreparation(plan), false);
  assert.equal(shouldRenderPreparationRuntime(plan), false);
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
      currentStageIndex: 1,
      currentStageLabel: "等待稳定 RUNNING",
      stages: [{
        index: 1,
        state: "waiting_stable",
        stateLabel: "等待稳定 RUNNING",
        current: true,
        nodes: [{ name: "MODULES:209-lightning", status: "STARTING", statusLabel: "启动中" }],
      }],
    },
  );
});

test("dependency preparation identifies the live stage and translates node state for operators", () => {
  assert.deepEqual(
    dependencyPreparationView({
      execution_preflight: { dependency_plan_enabled: true },
      execution_preflight_status: {
        updated_at: "2026-09-14T10:00:03+08:00",
        dependency_progress: {
          stages: [
            { index: 1, state: "waiting_stable", nodes: [{ name: "MODULES:209-lightning", status: "STARTING" }] },
            { index: 2, state: "pending", nodes: [{ name: "MODULES:211-navigate_todoor_server", status: "PENDING" }] },
          ],
        },
      },
    }),
    {
      visible: true,
      currentStageIndex: 1,
      currentStageLabel: "等待稳定 RUNNING",
      updatedAt: "2026-09-14T10:00:03+08:00",
      stages: [
        {
          index: 1,
          state: "waiting_stable",
          stateLabel: "等待稳定 RUNNING",
          current: true,
          nodes: [{ name: "MODULES:209-lightning", status: "STARTING", statusLabel: "启动中" }],
        },
        {
          index: 2,
          state: "pending",
          stateLabel: "待开始",
          current: false,
          nodes: [{ name: "MODULES:211-navigate_todoor_server", status: "PENDING", statusLabel: "待开始" }],
        },
      ],
    },
  );
});

test("dependency preparation identifies the first pending stage before a restart begins", () => {
  const view = dependencyPreparationView({
    execution_preflight: { dependency_plan_enabled: true },
    execution_preflight_status: {
      dependency_progress: {
        stages: [
          { index: 1, state: "pending", nodes: [] },
          { index: 2, state: "pending", nodes: [] },
        ],
      },
    },
  });

  assert.equal(view.currentStageIndex, 1);
  assert.equal(view.currentStageLabel, "待开始");
  assert.equal(view.stages[0].current, true);
  assert.equal(view.stages[1].current, false);
});

test("an active frozen plan owns the acceptance scope instead of a local draft", () => {
  assert.deepEqual(
    activeAcceptancePlanSelection({
      status: "running",
      scope_type: "building",
      community: "高科一号",
      building: 3,
      unit: 1,
      mode: "full",
      execution_preflight: {
        scenario_profile_id: null,
        dependency_plan_enabled: true,
        automatic_return_enabled: true,
      },
    }),
    {
      scope: "building",
      community: "高科一号",
      buildingUnit: "3:1",
      mode: "full",
      scenarioProfileId: "",
      dependencyPlanEnabled: true,
      automaticReturnEnabled: true,
    },
  );
});

test("terminal acceptance plans leave the browser draft available for the next plan", () => {
  assert.equal(
    activeAcceptancePlanSelection({ status: "completed", scope_type: "building" }),
    null,
  );
});

test("a ready plan leaves the acceptance scope editable until it starts", () => {
  assert.equal(
    activeAcceptancePlanSelection({
      status: "ready",
      scope_type: "community",
      community: "高科一号",
    }),
    null,
  );
});

test("a ready plan explicitly tells the operator that a new plan replaces it", () => {
  assert.equal(
    readyPlanReplacementNotice({ status: "ready" }),
    "计划尚未开始。可调整范围或运行准备后重新生成计划；新计划会替换当前未开始计划。",
  );
  assert.equal(readyPlanReplacementNotice({ status: "running" }), null);
});
