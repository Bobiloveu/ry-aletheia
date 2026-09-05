# 部署与地图配置

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/deployment.py`、`autodrive_console/mapping.py`、`web_console.py` 和部署 Web UI
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

现有部署 API 以 `/api/deployments` 开始。按项目划分的路由覆盖地图导入/上传、地图阶段、转场、路线、场景模型、地图实例、航点、组件模板/组件、虚拟墙和拓扑。建图会话由 `/api/mapping` 与 `/api/mapping/sessions` 路由控制。

Backend 校验具有权威性：客户端展示并提交用户意图，但不得直接写入部署文件或机器人配置。地图图像、元数据、虚拟墙和拓扑编辑都保留项目/地图所有权。

## Planned（规划中）

新的部署数据格式在成为跨客户端输入前，必须在 `shared/schemas` 中说明。Planned 字段在 Backend 暴露并完成校验前，始终保持 Planned 状态。

## Experimental task compiler

**Status: Experimental（已实现预览，不可部署）**
**权威实现：** `DeploymentStore` 的项目内实验导出与 `web_console.py` HTTP 路由
**消费者：** 当前仅 Web Console；Mobile 保持不变，在明确实现前不得调用以下路由。

编译器以一个 `ry-aletheia.site-project` 为唯一输入所有者，生成室内两图单电梯
场景的实验任务预览。它只能在该项目自己的 `deployments/<project_id>/exports/`
下持久化预览产物；不会写入 `/opt/ry/data/tasks/origin_tasks`、行为树运行目录或
定位运行配置，更不会启动 ROS、Supervisor 或下发任务。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/task-compiler/config` | 仅 `{ "community": "高科一号" }` | `{ "task_compiler": { "profile": "indoor_elevator_v1", "identity": { "community": "高科一号", "last_preview_input_sha256": null } } }` |
| `POST` | `/api/deployments/{project_id}/task-compiler/preview` | 空对象 `{}` | `{ "preview": { "status": "ready", "experimental": true, "input_sha256": "…", "task_json": { … }, "manifest": { … }, "derived_points": { … }, "artifacts": [ … ], "warnings": [], "errors": [], "statement": "实验产物，尚未安装到机器人。" } }` |
| `GET` | `/api/deployments/{project_id}/task-compiler/preview` | 无 | 同上；按当前 SiteProject 重新生成并保存项目内预览 |
| `GET` | `/api/deployments/{project_id}/task-compiler/download` | 无 | 仅返回实验 ZIP 附件；`Content-Type: application/zip`、UTF-8 `Content-Disposition`、`Content-Length` 和 `X-Content-Type-Options: nosniff` |

`project_id` 必须是单个既有 SiteProject 标识，客户端不传递输出文件名、导出路径或
运行时路径。配置请求的键必须严格等于 `community`，预览请求必须是空对象；后端仍会
对小区名称、地图、组件和编译输入做权威校验。

返回状态：格式、项目或存储错误为 `400 Bad Request`；项目事实不足、组件无效或当前
场景不属于已批准编译配置时为 `422 Unprocessable Entity`；成功预览与下载为 `200 OK`。
ZIP 是下载到操作员电脑的实验包，不构成安装、发布或机器人运行时写入授权。
