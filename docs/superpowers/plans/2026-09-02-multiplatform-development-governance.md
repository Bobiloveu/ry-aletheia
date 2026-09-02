# 多端开发环境与维护治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变核心目录和业务逻辑的前提下，为 RY Aletheia 建立按模块、操作系统和开发角色工作的可复现环境、契约和 CI 体系。

**Architecture:** Pixi 继续管理 Backend/Web，FVM 继续锁定 Flutter；根脚本只做统一转发。`doctor` 将 Profile 判断与宿主 OS 判断分开，Contracts 保持面向消费者的文档事实来源，CI 用路径过滤将 Backend、Web、Flutter 公共检查、Android 和 iOS 分开执行。

**Tech Stack:** Bash、PowerShell、Pixi、FVM、Flutter 3.47.1、GitHub Actions、Markdown、pytest。

**Spec:** `docs/superpowers/specs/2026-09-02-multiplatform-development-governance-design.md`

## Global Constraints

- 不移动、重命名或删除 Backend、Web、Mobile、Unity 的现有核心目录或源码文件。
- 不改变 ROS2 Topic、HTTP 业务语义、机器人速度限制或部署流程。
- 不要求 Windows/Linux 安装 Xcode，也不要求纯 Mobile 开发者安装 Pixi。
- 保留 `pixi.lock`、`.fvmrc`、`pubspec.lock`、`Podfile.lock`、SwiftPM `Package.resolved` 与 Gradle Wrapper 配置。
- Flutter 默认使用 CustomPaint 渲染，Unity 保持暂停且非默认。

---

### Task 1: 为 Profile Doctor 写可执行回归检查

**Files:**
- Modify: `tests/test_repository_conventions.py`
- Test: `tests/test_repository_conventions.py`

**Interfaces:**
- Produces: 对 `scripts/doctor.sh --help`、Profile 名称、Windows Doctor 文件、契约必填字段的静态保护。

- [ ] **Step 1: 写失败测试**

```python
def test_development_doctors_expose_supported_profiles():
    doctor = (ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    assert "mobile-android" in doctor
    assert "mobile-ios" in doctor
    assert (ROOT / "scripts" / "doctor.ps1").is_file()
```

- [ ] **Step 2: 运行并确认失败**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 失败，原因是 `doctor.ps1` 尚不存在且 Doctor 未声明目标 Profile。

- [ ] **Step 3: 最小实现测试断言**

在现有 repository convention 测试中加入上述断言与 Contract 字段断言，不修改业务测试。

- [ ] **Step 4: 再次运行测试**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 当前仍失败，直到 Task 2 与 Task 4 实现完成。

### Task 2: 实现按 Profile 的开发环境检查与安装入口

**Files:**
- Modify: `scripts/doctor.sh`
- Create: `scripts/doctor.ps1`
- Modify: `scripts/bootstrap.sh`
- Create: `scripts/README.md`

**Interfaces:**
- Consumes: `backend|web|mobile-android|mobile-ios|full` Profile 名称；旧 `mobile` 映射到 `mobile-android`。
- Produces: `./scripts/doctor.sh --profile <profile>` 和 `./scripts/bootstrap.sh <profile>`。

- [ ] **Step 1: 运行失败测试**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: Task 1 新测试失败。

- [ ] **Step 2: 最小实现**

在 Bash Doctor 中实现参数解析、OS 检测和 `OK/MISSING/OPTIONAL/UNSUPPORTED` 状态；在 PowerShell 中实现同一 Profile 语义；在 bootstrap 保留旧别名并增加 Android/iOS Profile。脚本只报告本机能力，不下载 SDK、不改变机器全局配置。

- [ ] **Step 3: 验证命令行为**

Run: `./scripts/doctor.sh --profile mobile-android && ./scripts/doctor.sh --profile mobile-ios && ./scripts/bootstrap.sh --help`

Expected: Android Profile 不以 Xcode 为必需项；macOS iOS Profile 明确检查 Xcode 与 CocoaPods；帮助文本同时列出兼容旧参数。

### Task 3: 固化环境规则与开发矩阵

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `mobile/README.md`
- Modify: `mobile/AGENTS.md`
- Modify: `mobile/docs/DEVELOPMENT_WORKFLOW.md`
- Create: `docs/development/README.md`
- Create: `docs/development/PROFILES.md`
- Modify: `AGENTS.md`
- Create: `scripts/README.md` (if not completed in Task 2)

**Interfaces:**
- Consumes: Task 2 Profile names and existing Pixi/FVM lock files.
- Produces: 文档中的唯一环境矩阵入口 `docs/development/PROFILES.md`。

- [ ] **Step 1: 写文档保护测试**

```python
def test_development_profile_document_is_linked_from_root_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/development/PROFILES.md" in readme
```

- [ ] **Step 2: 运行并确认失败**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 失败，原因是新文档与根 README 链接尚不存在。

- [ ] **Step 3: 最小实现文档**

新增按角色矩阵，明确 Pixi、FVM、Android JDK 17/Gradle 9.3.1/AGP 9.1.0、iOS 15.0/CocoaPods/SwiftPM、宿主平台限制和不要求安装的工具。根 README 与模块文档只链接权威页面，不复制整段安装说明。

- [ ] **Step 4: 验证链接与文本**

Run: `pixi run test -- tests/test_repository_conventions.py -q && git diff --check`

Expected: 测试通过且无空白错误。

### Task 4: 补全机器人控制 Shared Contract 与跨端影响规则

**Files:**
- Modify: `shared/contracts/README.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `AGENTS.md`
- Modify: `mobile/AGENTS.md`
- Modify: `frontend/AGENTS.md`
- Modify: `tests/test_repository_conventions.py`

**Interfaces:**
- Consumes: `VehicleControlConfig`、`VehicleControlController` 和 `/api/vehicle-control/*` 已有实现。
- Produces: 对 Topic、HTTP endpoint、状态枚举、方向枚举、速度范围、超时和消费者影响的稳定描述。

- [ ] **Step 1: 写失败测试**

```python
def test_robot_control_contract_contains_runtime_safety_rules():
    control = (ROOT / "shared/contracts/robot_control.md").read_text(encoding="utf-8")
    for required in ("navigation", "miniapp", "forward", "1.00", "heartbeat", "/api/vehicle-control/enter"):
        assert required in control
```

- [ ] **Step 2: 运行并确认失败**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 失败，原因是当前 Contract 缺少完整 HTTP 与运行时安全字段。

- [ ] **Step 3: 最小实现**

将当前已实现的事实补入 Contract，标记 Backend 为执行者、Web 为当前消费者、Mobile 为未来受控 API 消费者；为每项 Contract 标注受影响模块和修改流程。不得把 ROS publisher 或未来能力写成 Existing。

- [ ] **Step 4: 验证**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 通过，且静态测试能在契约被删减时失败。

### Task 5: 收紧可复现文件规则并拆分 CI

**Files:**
- Modify: `.gitignore`
- Modify: `mobile/.gitignore`
- Modify: `.github/workflows/module-checks.yml`
- Modify: `tests/test_repository_conventions.py`

**Interfaces:**
- Consumes: 现有 `pixi.lock`、`.fvmrc`、Flutter lock/native lock 文件与路径过滤。
- Produces: 后端/Web Linux、Flutter 公共 Linux、Android Linux、iOS macOS 分层校验。

- [ ] **Step 1: 写失败测试**

```python
def test_module_ci_has_android_and_ios_verification_jobs():
    workflow = (ROOT / ".github/workflows/module-checks.yml").read_text(encoding="utf-8")
    assert "android:" in workflow
    assert "ios:" in workflow
    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
```

- [ ] **Step 2: 运行并确认失败**

Run: `pixi run test -- tests/test_repository_conventions.py -q`

Expected: 失败，原因是现有 CI 只有统一 mobile job。

- [ ] **Step 3: 最小实现**

拆分 CI；Android job 执行 `fvm flutter build apk --debug`，iOS job 执行 `fvm flutter build ios --simulator --debug --no-codesign`。保留原 Backend/Web 命令，并让 Shared Contracts、锁文件和相关脚本触发受影响 job。Git ignore 只加入本地生成物，明确保留 lock/config 文件。

- [ ] **Step 4: 验证 YAML 与约定**

Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/module-checks.yml")' && pixi run test -- tests/test_repository_conventions.py -q`

Expected: YAML 可解析，约定测试通过。

### Task 6: 全量验证、审阅与合并

**Files:**
- Modify: `docs/AI_CONTINUATION.md` only if a continuation handoff is required.

- [ ] **Step 1: 运行针对性检查**

Run: `./scripts/doctor.sh --profile backend && ./scripts/doctor.sh --profile web && ./scripts/doctor.sh --profile mobile-android && ./scripts/doctor.sh --profile mobile-ios`

Expected: 当前 OS 的相关要求显示 OK/MISSING；不相关能力显示 OPTIONAL 或 UNSUPPORTED。

- [ ] **Step 2: 运行模块验证**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh && ./scripts/test-mobile.sh`

Expected: 各模块命令以零退出码结束。

- [ ] **Step 3: 运行原生构建验证**

Run: `./scripts/build-mobile.sh --platform android --debug && ./scripts/build-mobile.sh --platform ios --debug --simulator --no-codesign`

Expected: Android 与当前 macOS 上的 iOS 模拟器构建完成；若构建脚本不透传这些选项，使用已文档化的 FVM 等效命令并记录原因。

- [ ] **Step 4: 最终差异检查**

Run: `git diff --check && git status --short && git diff --stat`

Expected: 仅包含本计划的脚本、文档、约定测试、CI 与 ignore 变更，无构建产物、缓存、签名材料或 Golden 图片。
