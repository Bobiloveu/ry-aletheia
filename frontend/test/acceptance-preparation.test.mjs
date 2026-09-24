import assert from "node:assert/strict";
import test from "node:test";

import {
  activeAcceptancePlanSelection,
  acceptanceTaskPreview,
  acceptancePlanModePayload,
  acceptancePlanPreflightPayload,
  dependencyPreparationView,
  multiAcceptanceOptions,
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

test("task preview exposes the frozen ROS request without making it editable", () => {
  assert.deepEqual(
    acceptanceTaskPreview({
      filename: "1_1_2_201.json",
      parameters: { community: "数创大厦", building: 1, unit: 1, floor: 2, door: 201, execution_mode: "single_r6s" },
    }),
    {
      service: "/start_execute_tasks",
      serviceType: "master_interfaces/srv/StartExecuteTasks",
      modeLabel: "R6S 单点任务",
      fields: [
        ["community", "数创大厦"],
        ["building", 1],
        ["unit", 1],
        ["floor", 2],
        ["door", 201],
        ["task_uuid", ""],
      ],
      destinations: [],
    },
  );

  const preview = acceptanceTaskPreview({
    filename: "5_1_n_n01.json + 5_1_n_n01_return.json",
    parameters: { community: "数创大厦", building: 5, unit: 1, floor: 1, door: 101, execution_mode: "multi_r6b" },
    multi_request: {
      community: "数创大厦",
      out_eguard: false,
      return_origin: true,
      task_uuid: "task-001",
      tasks_seqs: [{ building: "5", unit: "1", floor: "1", door: "101", cargo_type: 1, delivery_code: "01" }],
    },
  });
  assert.equal(preview.service, "/start_multi_tasks_execute");
  assert.equal(preview.serviceType, "master_interfaces/srv/StartMultiTasksExecute");
  assert.equal(preview.modeLabel, "R6B 多点配送");
  assert.deepEqual(preview.fields.slice(0, 4), [
    ["community", "数创大厦"],
    ["out_eguard", false],
    ["return_origin", true],
    ["task_uuid", "task-001"],
  ]);
  assert.deepEqual(preview.destinations[0], [
    ["building", "5"],
    ["unit", "1"],
    ["floor", "1"],
    ["door", "101"],
    ["cargo_type", 1],
    ["delivery_code", "01"],
  ]);
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
      executionMode: "single_r6s",
      scenarioProfileId: "",
      dependencyPlanEnabled: true,
      automaticReturnEnabled: true,
    },
  );
});

test("R6B mode payload sends only generation controls while R6S stays isolated", () => {
  assert.deepEqual(
    acceptancePlanModePayload("multi_r6b", {
      outEguard: true,
      returnOrigin: false,
      chainMode: "chain",
      floorRanges: [{ building: 5, unit: 1, min_floor: 3, max_floor: 25 }],
    }),
    {
      execution_mode: "multi_r6b",
      multi_options: {
        out_eguard: true,
        return_origin: false,
        chain_mode: "chain",
        max_points_per_task: 10,
        floor_ranges: [{ building: 5, unit: 1, min_floor: 3, max_floor: 25 }],
      },
    },
  );
  assert.deepEqual(acceptancePlanModePayload("single_r6s", { destinations: [{ delivery_code: "ignored" }] }), { execution_mode: "single_r6s" });
});

test("R6B task-send defaults do not request outdoor transfer or return", () => {
  assert.deepEqual(multiAcceptanceOptions(), {
    out_eguard: false,
    return_origin: false,
    chain_mode: "single",
    max_points_per_task: 10,
    floor_ranges: [],
  });
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
