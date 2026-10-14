# PCD 地图导入与高度预览

用户已批准：仅上传 PCD、自动推荐高度、人工调整预览后确认生成；保留原来的引导式部署操作。工作在当前 v2.0 工作区进行，保留已有修改，不创建脱离这些修改的工作树，不提交、不编译、不升级、不触碰车辆运行配置。

## 操作流程

现有“地图来源”增加“PCD 生成二维地图”，原来的文件组合导入与车端建图保持兼容。PCD 流程依次为上传、后台分析、设置高度范围/分辨率/去噪、生成预览、确认导入。只有确认成功才推进到原来的地图阶段与拓扑引导。使用普通中文操作说明，不向用户展示内部标识或代码。

默认推荐来自点云高度分布和候选地面层，显示推荐依据与不确定性；允许选择不同候选地面，或直接精确填写绝对 Z 上下限。推荐仅为人工选择的起点，不承诺全自动判断地图可通行性。第一版采用水平高度区间；坡地的局部地面自适应不冒充已完成能力。

## 后台与数据

新增独立点云投影模块及项目级后台会话管理模块。通过开源 pypcd4 读取 ASCII、binary、binary_compressed，使用 NumPy 实现 pcd2pgm 同类高度筛选与占据栅格投影，不启动 ROS 节点、不发布 /map。依赖锁定，发布入口检查并收集依赖，但本次不执行构建。读取前检查头部、点数、展开大小；转换并发为一，点数上限 1000 万，展开上限 512 MiB，栅格上限 1600 万格。

原始 PCD 不修改。预览输出 map.pgm/map.yaml，保留原 XY 坐标、栅格左下角原点和 PGM 上下方向。无点不代表自由空间：基于全部输入点的 XY 足迹确定有观测支持的格子，其余为未知；界面明确这是离线投影，需检查门洞与通道。拒绝空截面、非法范围、超大栅格、损坏文件；调整参数使旧预览失效。单边上限 16384 格以限制 PNG 预览的逐行开销；仅保留当前有效预览，避免反复调整累积大型 PCD 副本。YAML 保存源摘要与参数指纹，确认前持久化导入意图并允许中断重试核对恢复。

会话保存在项目工作区 `.projections/`，包含输入摘要、源指纹、参数、结果、状态、进度与错误。切页/刷新通过后台 latest 查询恢复；进程重启后未完成工作标记为 interrupted，不继续展示 ready。状态为 analyzing/awaiting_parameters/processing/ready/failed/cancelled/imported/interrupted。确认必须提交当前预览 revision，防止旧参数预览被导入。重复确认返回已有地图，不能重复复制。导入继续复用 DeploymentStore.import_uploaded_map，index.txt 可选，不虚构索引。

## 接口（Backend / Desktop Web，Mobile 非消费者）

- POST `/api/deployments/{project}/map-projections`：multipart `file`，202 `{projection}`。
- GET `/api/deployments/{project}/map-projections/latest`：200 `{projection: object|null}`。
- GET `/api/deployments/{project}/map-projections/{id}`：200 `{projection}`。
- POST 同路径 `/preview`：JSON `{z_min,z_max,resolution,min_points,denoise}`，202 `{projection}`。
- GET 同路径 `/preview.png?revision=N`：仅 ready/imported 且 revision 相同返回 PNG。
- POST 同路径 `/confirm`：JSON `{label,revision}`，201 `{map,project}`。
- DELETE 会话路径：取消后台结果采用，保留原始输入。

projection 返回 id/project_id/state/progress/message/revision/analysis/parameters/result/map_asset_id；result 仅数据不含任意服务器文件路径。project 与会话所有权均由服务端校验。

## 验证

真实小型 PCD 覆盖三种编码、非有限坐标、不同字段顺序、截面边界、栅格端点、图像翻转、未知格、去噪及超限。后台覆盖异步状态、项目隔离、切页恢复、重启中断、旧 revision 拒绝和重复确认。HTTP 覆盖上传、参数错误与 PNG revision。Web 覆盖逐步任务、参数更改后不能确认、恢复与旧导入兼容，并用浏览器检查桌面/窄屏。Web 单元与 parity 单独运行，禁止执行包含 Vite 编译的 frontend-check。
