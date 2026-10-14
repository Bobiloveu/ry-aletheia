# 工具日志覆盖实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让工具各功能的操作、后台结果和浏览器异常进入现有诊断日志，便于还原问题。

**Architecture:** 在 HTTP 操作边界统一记录关联编号、功能、结果和耗时；后台模块记录实际生命周期；浏览器通过受控入口上报异常和本地处理失败。沿用现有 JSONL、轮转、错误分流和下载白名单。

**Tech Stack:** Python logging / HTTPServer、浏览器 JavaScript、pytest、Node tests。

**Spec:** `shared/contracts/tool_logging.md`。

## Global Constraints

- 保留现有工作区改动，不操作运行中的机器人或服务，不修改地图和现场任务数据。
- 原日志四个必填字段及 exception 保持兼容；新增上下文字段可选。
- 不记录请求正文、认证信息、图像、点云或逐帧数据；高频重复异常限流并记录恢复。
- 后台日志不能改变原有功能结果；测试使用临时目录和模拟对象。

### Task 1: HTTP 与日志基础设施

Files: `autodrive_console/tool_logging.py`, `autodrive_console/tool_audit.py`, `web_console.py`, `tests/test_tool_audit.py`。

- [x] 测试操作成功、拒绝、服务错误、异常、客户端断连、关联上下文和敏感字段清理。
- [x] 统一覆盖 API 写操作和编译、导出、下载等读取操作；轮询只记录故障边沿与恢复。
- [x] 配置日志先于服务构造，接入有界浏览器诊断入口。

### Task 2: 后台实际生命周期

Files: projection / recording / upgrade / inventory / acceptance / mapping / scenario / run / supervisor managers。

- [x] 排查现有日志并补齐开始、结束、取消、异常和恢复，修复错误 logger 命名空间。
- [x] 用模拟进程和临时目录验证结果与原行为一致。

### Task 3: 浏览器与本地操作

Files: `web/platform/client-diagnostics.js`, common HTTP helper, Vite entry injection, map/route workers and local export handlers。

- [x] 测试全局异常、加载失败、请求失败、限流、脱敏、重复安装与递归保护。
- [x] 所有第一方页面尽早安装；补齐被捕获的地图处理、路径规划、图片/软件清单导出失败。

### Task 4: 覆盖表与验收

- [x] 编写功能覆盖矩阵，说明关联字段、限流行为和排障方法。
- [x] 运行 Backend/Web 检查及现有 Mobile 日志解析的定向兼容检查。
- [x] 独立审查代码并修复发现的问题；不提交或打包运行产物。
