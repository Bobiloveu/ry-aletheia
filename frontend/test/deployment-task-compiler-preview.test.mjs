import assert from "node:assert/strict";
import test from "node:test";

import {
  isActivePreviewRequest,
  hasPersistedPreview,
  projectWithPreviewHash,
  previewMatchesProject,
} from "../../autodrive_console/web/deployment/task-compiler-preview.js";

test("successful task compiler preview is retained against its project input hash", () => {
  const project = {
    id: "project-1",
    task_compiler: { identity: { community: "高科一号" } },
  };
  const preview = { status: "ready", input_sha256: "preview-input-sha" };

  const updated = projectWithPreviewHash(project, preview);

  assert.notEqual(updated, project);
  assert.equal(updated.task_compiler.identity.last_preview_input_sha256, "preview-input-sha");
  assert.equal(previewMatchesProject(updated, preview), true);
  assert.equal(project.task_compiler.identity.last_preview_input_sha256, undefined);
});

test("persisted preview is restored only when its current project lacks a matching local preview", () => {
  const project = {
    task_compiler: { identity: { last_preview_input_sha256: "preview-input-sha" } },
  };

  assert.equal(hasPersistedPreview(project), true);
  assert.equal(previewMatchesProject(project, { input_sha256: "preview-input-sha" }), true);
  assert.equal(previewMatchesProject(project, { input_sha256: "stale-input-sha" }), false);
});

test("preview responses apply only to the project that started the request", () => {
  assert.equal(isActivePreviewRequest("project-a", { id: "project-a" }), true);
  assert.equal(isActivePreviewRequest("project-a", { id: "project-b" }), false);
  assert.equal(isActivePreviewRequest("project-a", null), false);
});
