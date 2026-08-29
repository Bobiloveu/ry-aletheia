# Aletheia Mobile 文档中心

本目录的文档以当前 Flutter 源码为依据，服务于交接、日常维护、UI Review 与多 Agent 并行开发。车端事实、协议与产品边界仍以仓库根目录的 [`PROJECT_OVERVIEW.md`](../../PROJECT_OVERVIEW.md) 为最高基线。

## 按角色阅读

| 角色 | 首先阅读 | 然后阅读 |
| --- | --- | --- |
| 新维护者 | [`../AGENTS.md`](../AGENTS.md)、[`../README.md`](../README.md) | [架构手册](ARCHITECTURE.md)、[开发工作流](DEVELOPMENT_WORKFLOW.md) |
| Flutter 功能开发 | [架构手册](ARCHITECTURE.md) | feature 源码、测试、[工作流](DEVELOPMENT_WORKFLOW.md) |
| UI/UX 开发与审查 | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md)、[`../../docs/UI_SPEC.md`](../../docs/UI_SPEC.md) | [UI Gallery 指南](../../docs/ui/README.md)、[Screen Inventory](../../docs/ui/SCREEN_INVENTORY.md) |
| 实时地图/视频维护 | [架构手册的实时观测章节](ARCHITECTURE.md#6-实时观测地图与视频) | [工作流的真机检查](DEVELOPMENT_WORKFLOW.md#7-真机与实时能力检查) |
| 处理构建/依赖/图标 | [工作流](DEVELOPMENT_WORKFLOW.md) | `pubspec.yaml`、`ios/`、`android/`、`tool/` |
| Agent 继续上次工作 | [`../../docs/AI_CONTINUATION.md`](../../docs/AI_CONTINUATION.md) | 本页及 `AGENTS.md` 的完整阅读顺序 |

## 核心文档

- [`../AGENTS.md`](../AGENTS.md)：协作规则、不可改动边界、并行任务文件所有权和交接要求。
- [`ARCHITECTURE.md`](ARCHITECTURE.md)：目录、路由、Provider、网络、地图、视频、设置、Gallery 和平台构建的源码级说明。
- [`DEVELOPMENT_WORKFLOW.md`](DEVELOPMENT_WORKFLOW.md)：本地启动、Debug Gallery、Golden、文档生成、真机、构建、图标与故障排查命令。
- [`../README.md`](../README.md)：产品能力、网络边界和快速运行入口。
- [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md)：移动端视觉 token、布局和组件约束。
- [`../../docs/UI_SPEC.md`](../../docs/UI_SPEC.md)：页面职责、信息架构与 UI 验收标准。

## UI Review 工件

这些文件由 Gallery manifest 和工具生成或维护，目的是审查真实页面的不同状态：

- [`../../docs/ui/README.md`](../../docs/ui/README.md)：Debug UI Gallery 使用方式。
- [`../../docs/ui/SCREEN_INVENTORY.md`](../../docs/ui/SCREEN_INVENTORY.md)：Route、状态、触发条件、Preview 和截图覆盖清单。
- [`../../docs/ui/SCREEN_MAP.md`](../../docs/ui/SCREEN_MAP.md)：按信息架构排列的 Screen Map。
- `../../docs/ui/screens/`：固定设备尺寸的截图输出目录（如已生成）。

不要手工编辑 `SCREEN_INVENTORY.md` 或 `SCREEN_MAP.md`；修改 `lib/debug_ui/gallery_manifest.dart` 后运行 `dart run tool/generate_ui_docs.dart` 重新生成。

## 文档维护规则

1. **架构文档记录稳定事实**：目录、所有权、传输边界和生命周期变化时必须同步更新。
2. **工作流记录可执行命令**：Flutter、Xcode、Gradle 或脚本变化时更新命令和输出位置。
3. **UI 文档记录已验收决定**：不把纯审美猜测写成产品需求；信息架构以 `PROJECT_OVERVIEW.md` 为准。
4. **Screen Inventory 是覆盖率登记，不是虚构功能列表**：只登记真实工程存在的页面或已实现状态。
5. **AI Continuation 是时效记录**：每轮更新顶部最新段落，旧记录保留供追溯。
6. 涉及协议、权限、命令能力或安全边界时，优先更新根目录 `PROJECT_OVERVIEW.md`；移动端文档只解释其消费方式。

## 文档变更自检

```sh
cd mobile
git diff --check
rg -n 'TODO|TBD|待确认' AGENTS.md README.md docs
dart run tool/generate_ui_docs.dart  # 仅 Gallery 清单变化时
```

如果文档描述与当前代码冲突，先在交接记录中标注，再以源码和最高事实基线校正；不要让过期文档引导实现。
