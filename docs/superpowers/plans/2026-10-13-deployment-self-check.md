# Deployment Self Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复全面自检发现的实际缺陷，用最终测试、浏览器和发布产物证明部署链路一致。
**Architecture:** 独立修复 Web 异步归属、Backend 编译校验、安装脚本权限；复用既有编辑快照、执行链及受控权限入口，不添加新的机器人动作。
**Tech Stack:** Python/Pytest、JS/Node tests、原生浏览器、Pixi、PyInstaller、DEB。
**Spec:** docs/superpowers/specs/2026-10-13-deployment-self-check.md

## Global Constraints

- 保留脏工作区与真实现场数据，不提交、部署或操作车辆/既有服务。
- Backend 与 PC Web 及安装脚本为本次消费者；Mobile 不消费部署编辑，不引入 Flutter 工具链。
- 先失败测试再最小修复；修复后验证原复现和邻接业务情况。
- 构建 2.8.3 ShmSDK ZIP+DEB，保留旧版本，全部产物核验后完成。

### Task 1: Web 异步归属

**Files:** deployment.js、必要的小模块、frontend/test/deployment/ 对应测试。
**Interfaces:** 消费现有项目选择/编辑快照；保护 DOM 和项目状态，不修改 API 线协议。

- [x] 基于 /tmp/ry-comprehensive-web-review.md 的三类复现添加失败回归。
- [x] 电梯草稿固定所属项目、地图、点、请求代次；关闭/切换后每个 await 都复核，旧请求不能读取新草稿。
- [x] 为任务信息、流程保存补齐与现有项目设置同等的响应归属保护；预览回来时再次检查线路草稿状态。
- [x] 运行定向测试与 Web 全量；独立复查旧响应和新编辑的交错情况。

### Task 2: Backend 编译一致性

**Files:** fixed_task_compiler.py、fixed_multi_export.py、必要几何辅助、Backend 回归测试、shared/contracts/deployment.md。
**Interfaces:** CompilationPreview 保持既有结构；失效配置返回 CompilationError，不新增运行时动作。

- [x] 基于 /tmp/ry-comprehensive-backend-review.md 添加三类失败回归，覆盖真实 Store 入口。
- [x] 校验公共源实例归属和 YAML resolution/origin 与资产一致；明确处理无效值，不误判正常全局摆渡层。
- [x] 检查候梯到中心、中心到到达候梯的直接设施重叠，无法按批准电梯语义表达时拒绝。
- [x] 运行相关编译、定位、目录、缓存、Store 检查并独立复查。

### Task 3: 安装权限边界

**Files:** packaging/debian/postinst、必要安装/权限测试。
**Interfaces:** 受控节点集合用于 start/restart；发现的日志节点单独用于 tail 规则；不改变车辆节点配置。

- [x] 用假的 supervisorctl status 复现日志节点错误获得 start/restart 权限。
- [x] 分离日志读取与控制节点列表，保留已有日志能力和明确批准的控制节点。
- [x] 验证日志专用节点没有控制规则、批准节点仍有正确规则、字符串转义和安装脚本语法通过。

### Task 4: 完整验收与发布

**Files:** 自检报告文档、忽略的 releases/2.8.3-shm/ 产物。
**Interfaces:** 前三项最终源码；输出测试、浏览器及归档证据。

- [x] 源码冻结后 scripts/test-backend.sh 完整运行、scripts/test-web.sh、test-offline、相关 doctor。
- [x] 当前项目只读副本验证 single/multi、ferry/indoor、起点位姿、通道节点、直接返程、XML 引用、模式/编辑缓存失效与 HTTP ZIP 一致。
- [x] 私有浏览器验证完成步骤编辑、去/返路线、异步切换保护、旋转/光标/美化关键交互。
- [x] 独立最终审查，处理所有重要发现；make_upgrade.sh 2.8.3 --shm --deb。
- [x] 验证签名/哈希、全部冻结业务代码和静态资源、DEB 安装规则及 --self-check，记录结果后完成目标。
