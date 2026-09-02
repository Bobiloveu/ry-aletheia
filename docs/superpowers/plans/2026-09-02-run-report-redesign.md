# 运行报告重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变运行与轨迹证据数据的前提下，生成 Apple 风格、离线可读且可打印的 Aletheia 单文件运行报告，并修复共享主题的浅色底色泄漏。

**Architecture:** 报告继续由 `RunManager._write_html_report()` 服务端生成；仅替换报告的语义结构和内嵌 CSS。共享主题的颜色变量移动至 `html[data-theme]`，`body` 保留兼容类；前端壳层同步该属性，避免页面空白区继承旧根节点深色。

**Tech Stack:** Python 3、unittest、原生 HTML/CSS/JavaScript、Aletheia 静态 Web 页面。

**Spec:** `docs/superpowers/specs/2026-09-02-run-report-redesign.md`

## Global Constraints

- 报告必须是可离线打开的单个 HTML 文件，不得引用外部资源。
- 不修改 ROS2、任务执行、轨迹采集、CSV 写入与报告下载路由。
- 保留 HTML 转义和 SVG 报告目录边界检查。
- 共享浅色主题由 `html[data-theme="light"]` 提供根变量，`body.theme-light` 仅为兼容标记。
- 运行报告仅显示真实运行数据，禁止制造示例状态或虚构图表。

---

### Task 1: 为独立报告建立结构回归测试

**Files:**
- Modify: `tests/test_offline_modules.py: test_downloadable_report_inlines_trajectory_svg`
- Modify: `autodrive_console/run_manager.py: RunManager._write_html_report`

**Interfaces:**
- Consumes: `RunManager._write_html_report(run: RunRecord, target: Path, csv_name: str) -> None`。
- Produces: 含有 `report-shell`、`report-summary`、`status-badge` 与内嵌 SVG 的单文件 HTML。

- [ ] **Step 1: Write the failing test**

```python
self.assertIn('class="report-shell"', contents)
self.assertIn('class="report-summary"', contents)
self.assertIn('class="status-badge completed"', contents)
self.assertIn('@media print', contents)
self.assertNotIn('https://', contents)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_downloadable_report_inlines_trajectory_svg -q`

Expected: FAIL because the existing report has no new report-shell semantic structure.

- [ ] **Step 3: Write minimal implementation**

Replace the existing report style and markup with self-contained semantic sections while keeping every value source, SVG boundary check and HTML escaping path intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_downloadable_report_inlines_trajectory_svg -q`

Expected: PASS.

### Task 2: 让生成报告适配真实证据阅读和打印

**Files:**
- Modify: `autodrive_console/run_manager.py: RunManager._write_html_report`
- Test: `tests/test_offline_modules.py: test_downloadable_report_inlines_trajectory_svg`

**Interfaces:**
- Consumes: 已有 `summary`、`rows`、`intervention_rows` 与 `evidence_html`。
- Produces: 包含摘要、运行上下文、结果表、人工处置表、证据段和打印规则的报告。

- [ ] **Step 1: Write the failing test**

```python
self.assertIn('地图运行轨迹证据', contents)
self.assertIn('人工干预与停滞处置记录', contents)
self.assertIn('CSV 伴随文件：unused.csv', contents)
self.assertIn('break-inside: avoid', contents)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_downloadable_report_inlines_trajectory_svg -q`

Expected: FAIL because the old report has no print-card layout contract.

- [ ] **Step 3: Write minimal implementation**

Add compact summary metrics, accessible status text and print-safe cards/tables without changing report data or adding JavaScript.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_downloadable_report_inlines_trajectory_svg -q`

Expected: PASS.

### Task 3: 修复全局主题根节点与手动控制空白区

**Files:**
- Modify: `autodrive_console/web/app_shell.js`
- Modify: `autodrive_console/web/app_shell.css`
- Modify: `autodrive_console/web/manual_control.css`
- Test: `tests/test_offline_modules.py`

**Interfaces:**
- Consumes: `localStorage` 中的 `ry-aletheia-theme` 与现有 `body.theme-light` 兼容类。
- Produces: `html[data-theme="light" | "dark"]` 的主题根变量和最小视口高度的页面 body。

- [ ] **Step 1: Write the failing test**

```python
shell = (WEB_ROOT / "app_shell.js").read_text(encoding="utf-8")
css = (WEB_ROOT / "app_shell.css").read_text(encoding="utf-8")
self.assertIn("document.documentElement.dataset.theme", shell)
self.assertIn('html[data-theme="light"]', css)
self.assertIn("min-height: 100dvh", css)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_theme_shell_uses_document_root_tokens -q`

Expected: FAIL because the test does not yet exist and root theme synchronization is absent.

- [ ] **Step 3: Write minimal implementation**

Synchronize one root `data-theme` attribute when the logo switches theme, retain body class for old selectors, set semantic tokens on root theme selectors, and change manual-control hardcoded surfaces to shared variables.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_theme_shell_uses_document_root_tokens -q`

Expected: PASS.

### Task 4: 验证与视觉审计

**Files:**
- Verify: `autodrive_console/run_manager.py`
- Verify: `autodrive_console/web/app_shell.css`
- Verify: `autodrive_console/web/manual_control.css`

- [ ] **Step 1: Run focused regression tests**

Run: `pytest tests/test_offline_modules.py::OfflineModuleTests::test_downloadable_report_inlines_trajectory_svg tests/test_offline_modules.py::OfflineModuleTests::test_theme_shell_uses_document_root_tokens -q`

Expected: PASS.

- [ ] **Step 2: Run static syntax checks**

Run: `python -m py_compile autodrive_console/run_manager.py && node --check autodrive_console/web/app_shell.js`

Expected: exit 0.

- [ ] **Step 3: Run Impeccable detector**

Run: `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --target autodrive_console/web/manual-control.html --format terminal`

Expected: no blocking issues; document any detector observation that cannot apply to an operate UI.

- [ ] **Step 4: Review changed-file diff**

Run: `git diff --check -- autodrive_console/run_manager.py autodrive_console/web/app_shell.js autodrive_console/web/app_shell.css autodrive_console/web/manual_control.css tests/test_offline_modules.py`

Expected: no whitespace errors.
