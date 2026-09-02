# RY Aletheia Monorepo 工程结构整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在不迁移高风险业务源码的前提下，建立可复现的模块边界、跨端契约、开发脚本、FVM、文档、Agent 规则与按路径 CI。

**Architecture:** 第一阶段采用逻辑 Monorepo。后端继续由根 web_console.py 和 autodrive_console/ 承载，Web 源码继续在 frontend/，Flutter 继续在 mobile/。新增 shared/、scripts/、docs/ 和规则文件只描述及编排现有模块，不引入第二套源码或运行时路径。

**Tech Stack:** Pixi 0.77 / Python 3.10 / pytest、Node 20 / npm / Vite / Vue / PixiJS、Flutter 3.47.1 / Dart 3.13.1 / FVM 4.3.0、Bash、GitHub Actions。

**Spec:** docs/superpowers/specs/2026-09-02-monorepo-normalization-design.md

**实施状态（2026-09-02）：** 第一阶段已完成并合并至 `v2.0`（`0d1f47e`）。保留后端、Web、Mobile、ROS2/C++ 与 Unity 的真实源码位置；已新增逻辑模块边界、`shared/contracts`、统一脚本、FVM、文档索引、Agent 规则与按路径 CI。根 Pixi 后端测试、Web 构建、FVM 静态分析与 152 个 Flutter 测试均通过；Android Debug APK 与 iOS Simulator 无签名构建均已通过。

## Global Constraints

- 不移动 web_console.py、autodrive_console/、frontend/、live_preprocessor/、mobile/、unity/、config/、tasks/、packaging/ 或根发布脚本。
- 保持 pixi install、pixi run test、pixi run frontend-check、pixi run verify、pixi run vue-preview 可用。
- 固定 Flutter 3.47.1 / Dart 3.13.1，不升级 Flutter、AGP、Gradle、Kotlin、Xcode 或 CocoaPods。
- Android 基线：AGP 9.1.0、Gradle 9.3.1、Kotlin 2.4.0、JDK 17；只警告环境不匹配。
- iOS 基线：Xcode 26.6 审计环境、iOS 15.0、Swift 5.0；保留 Podfile.lock 与两个 Package.resolved。
- Unity 是暂停 PoC；默认移动端命令只能构建 Flutter renderer。
- 不提交 build/cache/log/signing 资产，也不触碰已有 mobile/test/debug_ui/failures/ 调试图片。
- Existing API、ROS Topic、wire format、WebSocket 或数据模型变化必须先更新 shared/contracts/；本计划只归档既有事实，不更改协议。

---

## File Structure

| 路径 | 责任 |
| --- | --- |
| tests/test_repository_conventions.py | 不依赖 Flutter/ROS 的静态回归：模块入口、FVM pin、contracts、脚本和 CI。 |
| mobile/.fvmrc | Flutter 3.47.1 项目级 pin。 |
| shared/contracts/*.md | Existing/Planned 跨端契约事实来源。 |
| shared/{schemas,models,templates}/README.md | 共享目录准入规则，禁止复制业务实现。 |
| scripts/*.sh | 调用既有 Pixi/FVM/Flutter 命令的统一入口。 |
| AGENTS.md 与模块 AGENTS | 全局和模块边界。 |
| docs/{architecture,backend,web,mobile,protocols,deployment}/README.md | 索引；旧文档路径保持不变。 |
| .github/workflows/module-checks.yml | 路径过滤的 backend/web/mobile/contracts CI。 |

### Task 1: 建立静态整理回归测试与目录骨架

**Files:**
- Create: tests/test_repository_conventions.py
- Create: apps/README.md
- Create: shared/.gitkeep
- Create: scripts/.gitkeep

**Interfaces:**
- Consumes: 仓库根目录、既有 pixi.toml、mobile/pubspec.yaml。
- Produces: pytest 静态仓库约束；后续任务登记工件。

- [ ] **Step 1: 写失败测试**

    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]

    def test_logical_modules_keep_real_source_locations() -> None:
        assert (ROOT / "web_console.py").is_file()
        assert (ROOT / "autodrive_console").is_dir()
        assert (ROOT / "frontend" / "package.json").is_file()
        assert (ROOT / "mobile" / "pubspec.yaml").is_file()
        assert (ROOT / "live_preprocessor" / "CMakeLists.txt").is_file()
        assert (ROOT / "apps" / "README.md").is_file()

    def test_mobile_fvm_and_contract_catalog_are_pinned() -> None:
        assert (ROOT / "mobile" / ".fvmrc").read_text(encoding="utf-8").strip() == "3.47.1"
        for name in ("README.md", "robot_control.md", "realtime_observation.md", "video.md", "task_execution.md", "deployment.md"):
            assert (ROOT / "shared" / "contracts" / name).is_file()

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py  
Expected: FAIL，因为 FVM pin、contracts 和 apps README 尚不存在。

- [ ] **Step 3: 建立骨架但不创建影子源码**

apps/README.md 必须声明：后端实际入口仍为根 web_console.py 与 autodrive_console/，Web 仍为 frontend/，Mobile 仍为 mobile/；该目录只记录第二阶段迁移条件。

- [ ] **Step 4: 确认路径边界已锁定**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py  
Expected: FAIL 仅因后续 FVM/contracts 工件缺失；现有目录断言通过。

- [ ] **Step 5: Commit**

    git add tests/test_repository_conventions.py apps/README.md shared/.gitkeep scripts/.gitkeep
    git commit -m "test(repo): guard logical monorepo boundaries"

### Task 2: 固定 Flutter 环境并建立移动端命令边界

**Files:**
- Create: mobile/.fvmrc
- Modify: mobile/README.md
- Modify: mobile/docs/DEVELOPMENT_WORKFLOW.md
- Modify: mobile/AGENTS.md
- Modify: tests/test_repository_conventions.py

**Interfaces:**
- Consumes: mobile/pubspec.yaml（Dart ^3.13.1）、实际 Flutter 3.47.1、mobile/tool/build_mobile_packages.sh。
- Produces: 文档统一使用 fvm flutter；默认 renderer 明确为 Flutter。

- [ ] **Step 1: 扩展失败测试**

    def test_mobile_docs_use_fvm_and_keep_platform_locks() -> None:
        readme = (ROOT / "mobile" / "README.md").read_text(encoding="utf-8")
        workflow = (ROOT / "mobile" / "docs" / "DEVELOPMENT_WORKFLOW.md").read_text(encoding="utf-8")
        assert "fvm flutter pub get" in readme
        assert "fvm flutter analyze" in workflow
        assert (ROOT / "mobile" / "pubspec.lock").is_file()
        assert (ROOT / "mobile" / "ios" / "Podfile.lock").is_file()
        assert (ROOT / "mobile" / "ios" / "Runner.xcworkspace" / "xcshareddata" / "swiftpm" / "Package.resolved").is_file()

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py::test_mobile_docs_use_fvm_and_keep_platform_locks  
Expected: FAIL，现有文档使用裸 flutter 命令。

- [ ] **Step 3: 最小实现**

`mobile/.fvmrc` 使用 FVM 4 可识别的 JSON 格式：

    {
      "flutter": "3.47.1"
    }

在 README、workflow 和 AGENTS 中写入：

    dart pub global activate fvm 4.3.0
    cd mobile
    fvm install
    fvm flutter pub get
    fvm flutter analyze
    fvm flutter test
    fvm flutter run

记录 Android 的 Java 17/AGP 9.1.0/Gradle 9.3.1/Kotlin 2.4.0，iOS 的 iOS 15.0/Swift 5.0/CocoaPods+SwiftPM，以及 pubspec.lock、Podfile lock、SwiftPM lock 必须提交。不得改动 Android/iOS 配置或默认 Unity 状态。

- [ ] **Step 4: 验证**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py  
Expected: FVM 文档与 lock 断言 PASS。

Run: cd mobile && fvm flutter analyze  
Expected: 当前机器没有 FVM 时记录为环境 WARN；不得用全局 Flutter 伪造 FVM 成功。

- [ ] **Step 5: Commit**

    git add mobile/.fvmrc mobile/README.md mobile/docs/DEVELOPMENT_WORKFLOW.md mobile/AGENTS.md tests/test_repository_conventions.py
    git commit -m "chore(mobile): pin Flutter through fvm"

### Task 3: 建立 shared/contracts 与共享资料准入规则

**Files:**
- Create: shared/contracts/README.md
- Create: shared/contracts/robot_control.md
- Create: shared/contracts/realtime_observation.md
- Create: shared/contracts/video.md
- Create: shared/contracts/task_execution.md
- Create: shared/contracts/deployment.md
- Create: shared/schemas/README.md
- Create: shared/models/README.md
- Create: shared/templates/README.md
- Modify: tests/test_repository_conventions.py

**Interfaces:**
- Consumes: web_console.py 路由、autodrive_console/vehicle_control.py、autodrive_console/telemetry.py、Mobile repositories、frontend/src/liveObservation.js。
- Produces: Existing 契约的单一阅读入口。

- [ ] **Step 1: 写失败测试**

    def test_contracts_mark_existing_and_document_realtime_lanes() -> None:
        control = (ROOT / "shared" / "contracts" / "robot_control.md").read_text(encoding="utf-8")
        observation = (ROOT / "shared" / "contracts" / "realtime_observation.md").read_text(encoding="utf-8")
        assert "Status: Existing" in control
        assert "/control_source_cmd" in control
        assert "/control_source_state" in control
        assert "/cmd_vel_miniapp" in control
        assert "Status: Existing" in observation
        assert "ALTM v1" in observation
        assert all(port in observation for port in ("8768", "8769", "8770"))

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py::test_contracts_mark_existing_and_document_realtime_lanes  
Expected: FAIL，因为 contracts 文件尚不存在。

- [ ] **Step 3: 实现所有契约**

每个契约采用相同头部：Status: Existing、Authoritative implementations、Consumers、Compatibility。内容要求：
- robot_control.md：三个 ROS Topic、/api/vehicle-control 生命周期、运行中冲突、显式 stop/exit 安全语义。
- realtime_observation.md：RALT UDP ingress、ALTM v1、/cloud、/pose、8768/8769/8770、最多 3000 点、latest-wins、过期帧丢弃。
- video.md：/api/video/status、/api/video/control、WHEP/WebRTC 直连及 Python 不转发帧。
- task_execution.md、deployment.md：只写现有受控 HTTP 行为；未来能力在明确 Planned 小节。
- 三个 shared README：禁止放实现代码；新增 schema 必须由生产端和至少一个消费者测试覆盖。

- [ ] **Step 4: 验证**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py tests/test_vehicle_control.py tests/test_telemetry.py  
Expected: PASS。

- [ ] **Step 5: Commit**

    git add shared tests/test_repository_conventions.py
    git commit -m "docs(contract): centralize existing cross-client interfaces"

### Task 4: 新增统一脚本与 Pixi 兼容 alias

**Files:**
- Create: scripts/bootstrap.sh
- Create: scripts/doctor.sh
- Create: scripts/test-backend.sh
- Create: scripts/test-web.sh
- Create: scripts/test-mobile.sh
- Create: scripts/build-mobile.sh
- Modify: pixi.toml
- Modify: tests/test_repository_conventions.py

**Interfaces:**
- Consumes: 根 Pixi task、frontend/package.json、mobile/.fvmrc、mobile/tool/build_mobile_packages.sh。
- Produces: 非破坏性模块入口；旧 Pixi task 与新 alias 并存。

- [ ] **Step 1: 写失败测试**

    def test_scripts_delegate_to_existing_tools() -> None:
        backend = (ROOT / "scripts" / "test-backend.sh").read_text(encoding="utf-8")
        web = (ROOT / "scripts" / "test-web.sh").read_text(encoding="utf-8")
        mobile = (ROOT / "scripts" / "test-mobile.sh").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build-mobile.sh").read_text(encoding="utf-8")
        assert "pixi run test" in backend
        assert "pixi run frontend-check" in web
        assert "fvm flutter analyze" in mobile
        assert "fvm flutter test" in mobile
        assert "--engine flutter" in build
        assert "--engine unity" not in build

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py::test_scripts_delegate_to_existing_tools  
Expected: FAIL，因为 scripts 尚不存在。

- [ ] **Step 3: 实现最小脚本**

所有脚本以此开头：

    #!/usr/bin/env bash
    set -euo pipefail
    ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

- test-backend.sh：cd "$ROOT"; pixi run test
- test-web.sh：cd "$ROOT"; pixi run frontend-check
- test-mobile.sh：缺 FVM 则输出 dart pub global activate fvm 4.3.0 并 exit 2；否则在 mobile/ 运行 fvm flutter analyze && fvm flutter test
- build-mobile.sh：同样要求 FVM；运行 ./tool/build_mobile_packages.sh --engine flutter "$@"
- bootstrap.sh：默认打印 backend/web/mobile 初始化命令；显式参数 backend、web、mobile 或 all 才执行。all 逐端 WARN，不因缺 FVM 阻断 Pixi/Node 初始化。
- doctor.sh：用 ok、warn、fail 函数输出 [OK]、[WARN]、[FAIL]；Pixi 缺失为 FAIL，FVM/Android SDK/adb/Xcode/CocoaPods/Unity 缺失为 WARN，JDK 主版本非 17 为 WARN。

在 pixi.toml 添加但不重命名已有 task：

    backend-test = { depends-on = ["test"] }
    web-check = { depends-on = ["frontend-check"] }
    backend-run = "python web_console.py"

- [ ] **Step 4: 验证**

Run: chmod +x scripts/*.sh && bash -n scripts/*.sh  
Expected: PASS。

Run: ./scripts/doctor.sh  
Expected: Pixi/Node/Flutter/Dart/Xcode/CocoaPods 已安装项为 [OK]；FVM、JDK 26 和 Unity 状态为 [WARN]，不阻断。

Run: pixi task list && pixi run python -m pytest -q tests/test_repository_conventions.py && pixi run frontend-check && pixi run test-offline  
Expected: PASS，且旧 task 保留。

- [ ] **Step 5: Commit**

    git add scripts pixi.toml tests/test_repository_conventions.py
    git commit -m "chore(dev): add module entrypoints and pixi aliases"

### Task 5: 根与模块 Agent 规则、README 和文档索引

**Files:**
- Create: AGENTS.md, autodrive_console/AGENTS.md, frontend/AGENTS.md
- Create: docs/architecture/README.md, docs/architecture/module-boundaries.md, docs/architecture/monorepo-migration.md
- Create: docs/backend/README.md, docs/web/README.md, docs/mobile/README.md, docs/protocols/README.md, docs/deployment/README.md
- Modify: README.md, PROJECT_OVERVIEW.md, mobile/README.md, mobile/AGENTS.md, tests/test_repository_conventions.py

**Interfaces:**
- Consumes: Existing root docs, Mobile AGENTS, Task 3 contracts.
- Produces: 新开发者可定位模块、环境、契约和验证方式；Agent 不会误认为物理迁移已完成。

- [ ] **Step 1: 写失败测试**

    def test_docs_and_agent_rules_link_real_modules() -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for path in ("autodrive_console/AGENTS.md", "frontend/AGENTS.md", "mobile/AGENTS.md"):
            assert (ROOT / path).is_file(), path
        for section in ("architecture", "backend", "web", "mobile", "protocols", "deployment"):
            assert (ROOT / "docs" / section / "README.md").is_file(), section
        assert "shared/contracts" in agents
        assert "scripts/doctor.sh" in readme

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py::test_docs_and_agent_rules_link_real_modules  
Expected: FAIL，因为根/后端/Web AGENTS 和文档索引尚不存在。

- [ ] **Step 3: 实现规则和索引**

根 AGENTS 必须要求先读根 README、模块 README、相关 Existing contract；未经授权禁止物理迁移/业务重构；协议变化要更新 contracts 并检查消费者；只改目标模块；完成前跑验证；不提交生成物；Flutter 是主线、Unity 暂停。

后端 AGENTS：ROS2 只读/受控边界、运行数据与发布兼容、Pixi tests。  
Web AGENTS：Vite 输出仍为 ../autodrive_console/web-vue，浏览器不直接调用 ROS。  
Mobile AGENTS：只增补 FVM、平台 lock、默认 Flutter renderer 和 FVM 验证，保留原有规则。

根 README 只留下项目是什么、真实模块位置、按角色最小命令、docs/contract 入口。PROJECT_OVERVIEW.md 继续承载详细工程事实，并在开头链接 architecture 与 contracts。新 docs README 只作索引，不搬运 docs/ui/、docs/images/、docs/superpowers/、mobile/docs/ 原文。

- [ ] **Step 4: 验证**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py && git diff --check  
Expected: PASS。

- [ ] **Step 5: Commit**

    git add AGENTS.md autodrive_console/AGENTS.md frontend/AGENTS.md mobile/AGENTS.md README.md PROJECT_OVERVIEW.md docs tests/test_repository_conventions.py
    git commit -m "docs: define monorepo module boundaries"

### Task 6: 添加按模块 CI

**Files:**
- Create: .github/workflows/module-checks.yml
- Modify: tests/test_repository_conventions.py

**Interfaces:**
- Consumes: Pixi lock/tasks、frontend lock、mobile FVM pin、contracts。
- Produces: PR/push 按影响路径检查，不含签名、Unity 或 ROS2 发布构建。

- [ ] **Step 1: 写失败测试**

    def test_ci_is_split_by_module_and_excludes_unity_builds() -> None:
        workflow = (ROOT / ".github" / "workflows" / "module-checks.yml").read_text(encoding="utf-8")
        for job in ("backend:", "web:", "mobile:", "contracts:"):
            assert job in workflow
        for path in ("autodrive_console/**", "frontend/**", "mobile/**", "shared/contracts/**"):
            assert path in workflow
        assert "flutter analyze" in workflow
        assert "flutter test" in workflow
        assert "unity" not in workflow.lower()

- [ ] **Step 2: 确认红灯**

Run: pixi run python -m pytest -q tests/test_repository_conventions.py::test_ci_is_split_by_module_and_excludes_unity_builds  
Expected: FAIL，因为 workflow 尚不存在。

- [ ] **Step 3: 实现 workflow**

使用 dorny/paths-filter@v3 的 changes job：
- backend：web_console.py、autodrive_console/**、live_preprocessor/**、config/**、tasks/**、packaging/**、build_*.sh、pixi.toml、pixi.lock、tests/**
- web：frontend/**、autodrive_console/web/**
- mobile：mobile/**
- contracts：shared/contracts/**

backend 在 backend/contracts 改动时安装 Pixi 并执行 pixi run test。  
web 在 web/contracts 改动时安装 Pixi 并执行 pixi run frontend-check。  
mobile 在 mobile/contracts 改动时使用 Flutter 3.47.1、激活 FVM 4.3.0，并在 mobile/ 执行 fvm flutter pub get、fvm flutter analyze、fvm flutter test。  
禁止 Android/iOS 打包、签名、Unity、ROS2 和部署步骤进入 workflow。

- [ ] **Step 4: 验证**

Run: pixi run python -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/module-checks.yml").read_text()); print("workflow yaml ok")'  
Run: pixi run python -m pytest -q tests/test_repository_conventions.py  
Expected: PASS。

- [ ] **Step 5: Commit**

    git add .github/workflows/module-checks.yml tests/test_repository_conventions.py
    git commit -m "ci: run checks by affected module"

### Task 7: 全量验证、Git 卫生与交接

**Files:**
- Modify: docs/AI_CONTINUATION.md
- Modify: 设计与本计划状态字段

**Interfaces:**
- Consumes: Tasks 1–6。
- Produces: 可复现交接状态、验证记录和第二阶段前置条件。

- [ ] **Step 1: 更新交接记录**

在 docs/AI_CONTINUATION.md 追加 Monorepo 第一阶段：保留原位的后端/Web/Mobile/Unity 路径、FVM 3.47.1、Pixi 责任、contracts、scripts、CI、Unity 暂停与第二阶段条件。

- [ ] **Step 2: 运行不依赖 FVM/ROS 的完整验证**

Run: pixi install && pixi run test && pixi run frontend-check && pixi run verify  
Run: bash -n scripts/*.sh run_vue_preview.sh && ./scripts/doctor.sh  
Expected: Pixi 验证通过；doctor 对缺失 FVM/JDK 非 17/Unity 只 WARN。

- [ ] **Step 3: 运行 Mobile 验证或如实记录环境阻塞**

Run: cd mobile && fvm install && fvm flutter pub get && fvm flutter analyze && fvm flutter test  
Run: cd mobile && fvm flutter build apk --debug  
Run: cd mobile && fvm flutter build ios --simulator --debug --no-codesign  
Expected: 条件满足则 PASS；若 FVM 未安装、SDK 下载受限、JDK 非 17 或 Android SDK 缺失，记录阻塞，绝不以全局 Flutter 或签名发布构建替代。

- [ ] **Step 4: Git hygiene**

Run: git diff --check && git status --short  
Expected: 不新增 .pixi/、node_modules、build、dist、releases、logs、签名资产或 Golden failure 图片。保留并单列任务开始前的 pixi.toml、pixi.lock、run_vue_preview.sh 与 failure 图片改动，除非明确纳入独立提交。

- [ ] **Step 5: Commit**

    git add docs/AI_CONTINUATION.md docs/superpowers/specs/2026-09-02-monorepo-normalization-design.md docs/superpowers/plans/2026-09-02-monorepo-normalization.md
    git commit -m "docs: record monorepo normalization handoff"
