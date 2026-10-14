# 手动场景诊断录包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让操作者在不发任务的情况下开始、停止和定时结束受控 ROS 2 诊断录包。

**Architecture:** `BagRecordingManager` 保持 recorder、审查和归档所有权；新增线程安全的 `ManualRecordingController` 管理一条手动会话和 Backend deadline。Web 在诊断录包页显示受控的开始/停止状态，Topic 配置页使用独立的 manual session 草稿。

**Tech Stack:** Python 3.10、rclpy/rosbag2、HTTP `BaseHTTPRequestHandler`、原生 ES modules、Node test、pytest。

**Spec:** `docs/superpowers/specs/2026-10-09-manual-diagnostic-bag-recording-design.md`

## Global Constraints

- 不发任务、不发布控制 Topic、不修改机器人配置，也不自动打包、上传或升级。
- 手动录制仅允许 1–32 个现有可录 DDS Topic；继续排除共享内存图像、点云和 LaserScan。
- 时长只允许 5、15、30、60 分钟，默认 30 分钟；Backend deadline 是唯一权威。
- 手动与自动测试录包互斥；浏览器切页或关闭不停止手动录制。
- 所有新用户文案使用中文，不显示命令、路径、环境变量或内部错误码。

---

### Task 1: 受控手动会话与归档来源

**Files:**
- Modify: `autodrive_console/bag_recording.py`
- Create: `autodrive_console/manual_bag_recording.py`
- Test: `tests/test_manual_bag_recording.py`

**Interfaces:**
- Produces `ManualRecordingRequest(topics: tuple[str, ...], duration_minutes: int, label: str)`.
- Produces `ManualRecordingController.status()`, `start(payload)`, `stop(reason="operator")`, and `has_active_recording()`.
- Consumes `BagRecordingManager.start_manual(request)` and `BagRecordingManager.stop(active)`.

- [ ] **Step 1: Write failing tests** for valid duration/name/topic requests, timer expiry, explicit-stop race, and archive source fields.
- [ ] **Step 2: Run** `pixi run bash -c 'unset PYTHONPATH; python -m pytest tests/test_manual_bag_recording.py -q'`; expect missing module or methods.
- [ ] **Step 3: Implement** a narrow `ManualRecordingController` that holds one active record under `RLock`, schedules deadline with `threading.Timer`, and uses a finalizing latch.
- [ ] **Step 4: Extend** `BagRecordingManager` with a manual start path that uses the same fixed argv, environment verifier, counter and atomic audit path, while adding safe source/label/duration metadata.
- [ ] **Step 5: Run** the Task 1 tests and `tests/test_bag_recording.py`; expect all pass.

### Task 2: HTTP boundary and test-run mutual exclusion

**Files:**
- Modify: `web_console.py`
- Modify: `autodrive_console/run_manager.py`
- Modify: `shared/contracts/task_execution.md`
- Test: `tests/test_bag_recording_http.py`, `tests/test_manual_bag_recording.py`, `tests/test_run_manager.py`

**Interfaces:**
- Produces `GET/POST /api/bag-recordings/manual` and `POST /api/bag-recordings/manual/stop`.
- Consumes controller status without exposing recorder argv, output paths or environment.

- [ ] **Step 1: Write failing HTTP tests** asserting exact valid payload, active-state response, conflict during active recording, and stop semantics.
- [ ] **Step 2: Run** the selected pytest tests; expect the new routes to fall through or fail assertions.
- [ ] **Step 3: Implement** input-size/schema validation and status serialization in `ConsoleHandler`; construct one controller at console startup.
- [ ] **Step 4: Add** one explicit gate before test-attempt recording and before manual start so the two recorder modes cannot overlap.
- [ ] **Step 5: Update** the contract with consumers, request/response schemas, mutual exclusion and retention semantics.
- [ ] **Step 6: Run** affected tests; expect all pass.

### Task 3: Independent manual Topic selection and user interface

**Files:**
- Modify: `autodrive_console/web/bag-recording-selection.js`
- Modify: `autodrive_console/web/bag-recording-config.html`
- Modify: `autodrive_console/web/bag-recording-config.js`
- Modify: `autodrive_console/web/bag-recordings.html`
- Modify: `autodrive_console/web/bag_recordings.js`
- Modify: `autodrive_console/web/bag_recordings.css`
- Test: `frontend/test/legacy-app-module.test.mjs`

**Interfaces:**
- Produces `loadManualBagRecordingDraft` and `saveManualBagRecordingDraft` with only a Topic list.
- Consumes `/api/bag-recordings/manual` and the existing Topic discovery endpoint.

- [ ] **Step 1: Write failing browser-module and markup tests** for a separate manual draft, 5/10/15/20 duration choices, manual recording copy, and no raw recorder details.
- [ ] **Step 2: Run** `pixi run node --test frontend/test/legacy-app-module.test.mjs`; expect new assertions to fail.
- [ ] **Step 3: Implement** manual-mode query handling in the configuration page and an archive-page control panel with start, status poll, timer and stop actions.
- [ ] **Step 4: Render** manual archives with readable scene name/duration while leaving existing test archive cards compatible.
- [ ] **Step 5: Run** the Web module test; expect all pass.

### Task 4: Review and multi-round verification

**Files:**
- Verify: files from Tasks 1–3
- Test: `tests/test_bag_recording.py`, `tests/test_manual_bag_recording.py`, `tests/test_bag_recording_http.py`, `tests/test_run_manager.py`, `frontend/test/legacy-app-module.test.mjs`

- [ ] **Step 1: Run** backend tests twice from a clean `PYTHONPATH`:
  `pixi run bash -c 'unset PYTHONPATH; python -m pytest tests/test_bag_recording.py tests/test_manual_bag_recording.py tests/test_bag_recording_http.py tests/test_run_manager.py -q'`.
- [ ] **Step 2: Run** the Web module test twice:
  `pixi run node --test frontend/test/legacy-app-module.test.mjs`.
- [ ] **Step 3: Run** `pixi run python -m py_compile web_console.py autodrive_console/bag_recording.py autodrive_console/manual_bag_recording.py` and `git diff --check` for touched paths.
- [ ] **Step 4: Review** HTTP schemas and rendered static pages using a local server; verify manual topic selection, start/stop state, and test/manual draft isolation.
- [ ] **Step 5: Do not package, upload or upgrade.** Report that real recorder validation requires explicit deployment authorization and a live ROS environment.
