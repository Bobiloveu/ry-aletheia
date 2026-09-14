import assert from "node:assert/strict";
import test from "node:test";

import { caseDeleteConfirmationText } from "../../autodrive_console/web/case_library_delete.js";

test("case deletion confirmation names the exact local task asset", () => {
  assert.equal(
    caseDeleteConfirmationText("高科一号_1_1_15_0.json"),
    "删除 高科一号_1_1_15_0.json？此操作会从本机任务目录永久移除该用例。",
  );
});
