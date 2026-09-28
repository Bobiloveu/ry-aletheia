import assert from "node:assert/strict";
import test from "node:test";

import { deleteDeploymentAnnotation } from "../../../autodrive_console/web/deployment/annotation-delete.js";

test("component deletion refreshes the active project after the component endpoint succeeds", async () => {
  const calls = [];
  const notices = [];

  const result = await deleteDeploymentAnnotation({
    projectId: "site-5",
    annotation: { id: "component-narrow", label: "窄通道" },
    collection: "components",
    request: async (url, options) => {
      calls.push({ url, options });
      return { deleted: true };
    },
    refreshProject: async (projectId) => calls.push({ refreshProject: projectId }),
    notify: (message, error = false) => notices.push({ message, error }),
  });

  assert.equal(result, true);
  assert.deepEqual(calls, [
    {
      url: "/api/deployments/site-5/components/component-narrow",
      options: { method: "DELETE" },
    },
    { refreshProject: "site-5" },
  ]);
  assert.deepEqual(notices, [
    { message: "正在删除窄通道…", error: false },
    { message: "窄通道已删除；系统已根据剩余标记重新计算路线。", error: false },
  ]);
});

test("failed annotation deletion keeps the current project intact and reports the retryable error", async () => {
  const notices = [];
  let refreshed = false;

  await assert.rejects(
    () => deleteDeploymentAnnotation({
      projectId: "site-5",
      annotation: { id: "waypoint-transition", label: "过渡点" },
      collection: "waypoints",
      request: async () => { throw new Error("网络连接失败"); },
      refreshProject: async () => { refreshed = true; },
      notify: (message, error = false) => notices.push({ message, error }),
    }),
    /网络连接失败/,
  );

  assert.equal(refreshed, false);
  assert.deepEqual(notices, [
    { message: "正在删除过渡点…", error: false },
    { message: "删除过渡点失败：网络连接失败。请检查连接后重试。", error: true },
  ]);
});
