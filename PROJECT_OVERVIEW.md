# RY Aletheia 工程手册

> 面向维护、开发、构建与现场排障人员。日常安装、使用和升级请优先阅读 [README.md](README.md) 与 `releases/<版本>/README.md`。

## 1. 工程定位与边界

RY Aletheia 是部署在机器人小车 Ubuntu 主机上的离线自动驾驶测试平台。测试人员通过同一 Wi-Fi 下的浏览器访问 `http://<小车IP>:8087`；任务调用、ROS2 通信、Supervisor 操作、地图缓存与报告生成均在小车本机完成。

它负责测试编排、证据记录和只读观测，不替代小车原有的导航、定位、地图服务或安全控制。

- 任务仅通过既有 `/start_execute_tasks` 服务下发，不向底盘或导航发布控制指令。
- 不修改任务 JSON；别名、依赖编排和场景方案均保存在工具配置目录。
- 场景前置配置只替换启动脚本中已登记的 FCRP 与 lightning 参数，具备预览、备份、原子替换和恢复。
- 实时观测采用“时效优先”：过期帧直接丢弃，不追赶历史画面。
- 小车运行阶段不依赖互联网、Node.js、npm 或开发源码；主程序必须以普通账户运行。

## 2. 功能域

| 功能域 | 核心能力 |
| --- | --- |
| 测试用例管理 | 扫描 `tasks/` 任务 JSON、保存别名、绑定每条用例的场景前置方案，并以可校验用例包跨车交付。 |
| 测试指挥台 | 多轮串行执行、任务文件同步、依赖预检、Supervisor 编排、人工恢复和终止。 |
| 场景前置配置 | 选择 FCRP `.launch.py` 与 lightning YAML，受控替换 `handle_modules.sh`，测试结束自动恢复。 |
| 多地图轨迹 | 缓存实际地图，叠加实际轨迹、理想路线、虚拟墙并归档。 |
| 报告中心 | 生成、预览、下载、删除可离线查看的单文件 HTML 报告。 |
| 实时运行观测 | 地图、虚拟墙、车体轮廓、定位、点云和按需图像话题。 |
| 运行配置 | 依赖编排、车型、实时观测、升级和持久化设置。 |
| 工具日志 | 独立记录升级、ROS2、Bridge、观测和异常诊断。 |

## 3. 总体架构

```text
同网段浏览器
  │ HTTP :8087（控制台、API、报告）
  │ WebSocket :8767（默认，实时观测直连）
  ▼
RY Aletheia（普通账户）
  ├─ Python 控制台：计划、任务、Supervisor、轨迹、报告、配置、升级
  ├─ C++ 轻量预处理：/livox/points → /aletheia/live_points
  └─ Aletheia 私有 Foxglove Bridge（按需运行）
       ├─ ROS2：/map、/odom、TF、/amcl_pose、/start_execute_tasks、/livox/points
       ├─ Supervisor：受限 sudo supervisorctl status/start/restart
       └─ 运行数据：tasks、config、reports、maps_cache、updates、logs
```

测试执行经 HTTP API 进入 `RunManager`。实时观测则由浏览器直连 Aletheia 私有 Bridge，不再经过 `8087 → Python → Bridge` 中转，避免 Python 复制高频点云/图像造成额外延迟。

## 4. 目录与数据所有权

| 目录 / 文件 | 用途 | 升级 ZIP 是否覆盖 |
| --- | --- | --- |
| `dist/ry-aletheia` | 最终控制台二进制 | 是 |
| `tasks/` | 测试任务 JSON | 否 |
| `config/console.json` | 运行、依赖、车型、观测配置 | 否 |
| `config/scenario_setup.json` | 场景方案与用例绑定 | 否 |
| `config/case_workspace.json` | 用例版本、状态、标签、说明、来源与任务指纹 | 否 |
| `config/scenario_backups/` | 场景应用时的常规配置备份 | 否 |
| `reports/` | HTML/CSV 报告与轨迹证据 | 否 |
| `maps_cache/` | 地图、虚拟墙、观测底图缓存 | 否 |
| `updates/` | 升级暂存与唯一 `.bak` 备份 | 否 |
| `logs/` | 控制台、Bridge、预处理与错误日志 | 否 |
| `autodrive_console/` | Python 业务源码、正式网页输出 | 仅构建时 |
| `frontend/` | Vue/Vite 源码 | 仅开发机 |
| `live_preprocessor/` | C++ 点云预处理节点源码 | 仅构建时 |
| `install/`、`cpp_sdk/` | 目标小车导出的离线构建依赖 | 仅开发机 |
| `releases/` | ZIP、校验文件和可选 DEB 交付物 | 开发机输出 |

升级必须只替换程序产物，不能覆盖任务、报告、缓存或用户配置。

## 5. 后端模块职责

| 模块 | 职责 |
| --- | --- |
| `web_console.py` | HTTP 入口、静态资源、API、下载与安全退出。 |
| `case_store.py` | 用例 JSON 校验与扫描。 |
| `case_workspace.py` | 本机用例元数据、SHA-256 指纹、`.rycase.zip` 导入导出与冲突保护。 |
| `settings.py` | `console.json` 默认值、迁移、校验、原子保存。 |
| `models.py` | 计划、轮次、人工干预和统计模型。 |
| `run_manager.py` | 执行状态机、预检、恢复、场景应用/恢复、报告编排。 |
| `ros_executor.py` | ROS2 `/start_execute_tasks` 客户端。 |
| `runtime_env.py` | ROS2 环境探测与兼容降级。 |
| `robot_gateway.py` | 任务文件同步和受控本机操作。 |
| `supervisor.py` | Supervisor 状态解析、阶段编排、start/restart 与稳定等待。 |
| `scenario_setup.py` | 启动脚本识别、受控浏览、方案预览/应用/恢复、事务备份。 |
| `trajectory.py` | `/map`、`/odom`、TF 采集，多地图会话、进度与停滞检测。 |
| `navigation_status.py` | 电梯任务阶段识别，抑制合理等待期间的误告警。 |
| `map_assets.py` / `trajectory_render.py` | 地图、路线、虚拟墙缓存及轨迹 SVG 渲染。 |
| `observation.py` | 私有 Bridge/C++ 预处理生命周期、地图缓存和观测诊断。 |
| `tool_logging.py` | 工具级日志。 |
| `upgrade_manager.py` | 清单/MD5 校验、备份、原子替换与重启交接。 |

## 6. 测试执行状态机

```text
queued → preparing → running → completed
                    │
                    ├─ 单轮失败 → awaiting_recovery → recovering → running
                    │                         │
                    │                         └─ 终止 → cancelled
                    └─ 终止剩余轮次 → cancelling → cancelled
```

一次轮次严格按以下顺序执行：

1. 校验计划、任务文件和运行互斥状态。
2. 应用用例绑定的场景方案，并验证替换结果。
3. 等待方案应用后的稳定窗口。
4. 按依赖编排阶段 `restart` 节点；STOPPED 节点使用 `start`。
5. 每阶段等待所有依赖稳定为 `RUNNING`，再进入下一阶段。
6. 同步任务文件（仅目标目录没有同名文件时复制），确认 ROS2 服务可用。
7. 下发任务，开始轨迹和轮次记录。
8. 单轮失败后等待人工恢复；恢复后重新应用方案和依赖编排才允许继续。
9. 计划完成、取消或不可恢复失败后，自动恢复原常规启动配置。

节点名称、默认预检集、阶段顺序与等待时间必须由配置驱动，不能在业务代码中写死某一台车的节点名。

## 7. 场景前置配置安全模型

该模块不是通用文件编辑器。它用来避免测试人员手动改错启动脚本：

- 默认脚本为 `/opt/ry/scripts/handle_modules.sh`，可受控配置实际路径。
- 只识别 `ros2 launch fcrp_bringup ...` 和 `ros2 run lightning run_loc_online --config ...` 的参数位置。
- 只能按层浏览脚本所在受控目录树，不递归扫描整机文件系统。
- FCRP 仅可选择 `.launch.py`；lightning 仅可选择 `.yaml`/`.yml`。
- 应用前可预览完整替换结果；应用时保存原文、SHA-256、时间与方案 ID。
- 使用临时文件加原子替换；存在未恢复方案时拒绝再次应用。
- 用例仅保存方案 ID 绑定；删除方案前必须解除相关绑定。

任何扩展都必须维持“白名单参数位置、受控根目录、可恢复事务”三项边界。

## 8. 多地图轨迹与报告原则

- 从任务 JSON 提取全部 `map_url`，支持 P1/P2/P3 及更多地图。
- 结合 `/map` 签名与 map_server 元数据识别实际切图，不能只依赖文件名或 `map_load_time`。
- `/odom` 必须按消息时间经 TF 转为 `map` 坐标后记录；坐标不匹配时拒绝该点，不猜测。
- 同一地图多次进入时保留独立轨迹段，不能跨切图连接直线。
- 报告按地图分段：实际轨迹按任务/去返分色，理想路线为细虚线，虚拟墙为红色实线。
- 报告优先显示用例别名；轨迹图片内联，下载后仍可离线查看。

轨迹只反映定位输出，不能替代定位标定或平滑度评估。

## 9. 实时运行观测的工程策略

### 9.1 分层渲染

```text
静态地图栅格 + 虚拟墙  ─┐
点云 Canvas（Worker 合成） ├─ CSS 变换：缩放、拖动、航向旋转
车体 DOM 覆盖层           ┘
```

地图、虚拟墙在首次取得或切图时缓存；拖动、缩放、位姿和点云更新都不应重绘静态底图。缩放以鼠标位置为中心，中键或左键拖动仅改变视图变换。

### 9.2 时效优先与背压

| 数据 | 策略 | 时效边界 |
| --- | --- | --- |
| 点云 | C++ `keep_last(1)`，最多 10Hz、3000 点；Worker 单槽处理 | 输入超过 180ms 丢弃 |
| 位姿 | C++ 发布最新 `map → base_*` TF，浏览器独立动画 | 超过 120ms 丢弃；30Hz 显示 |
| 浏览器 WebSocket | 点云与位姿均为容量 1 的 latest-wins 队列 | 新包覆盖未解码旧包 |
| 地图 | 短订阅读取；仅切图时再更新 | 不持续传输大栅格 |
| 图像 | 仅订阅用户选中的话题，优先最新压缩帧 | 不追赶旧图像 |

短暂 Wi-Fi 抖动时允许跳帧，但恢复后必须尽快回到实车当前状态，不能显示数秒前的历史画面。

### 9.3 C++ 预处理节点

`live_preprocessor/` 的 `ry_aletheia_live` 仅服务本工具，不改动原自动驾驶节点：

- 输入 `/livox/points` 或 Livox 原生 `CustomMsg`。
- 输出已投影到 `map` 的 `/aletheia/live_points` 及 `/aletheia/live_pose`。
- 只接受标准 `float32 x/y/z`，限制距离、均匀抽样、QoS depth=1。
- 超时输入在 TF 查找和坐标转换前丢弃；TF 不可用则跳过当前帧。
- 不使用 PCL、不改写原 ROS 话题、不写导航参数。

现场排障优先看 `logs/live_preprocessor.log`、`logs/foxglove_bridge.log` 和工具日志，再检查 `/aletheia/live_points`、`/aletheia/live_pose` 的频率与时间戳。

## 10. 前端维护

前端源位于 `frontend/src/`，构建产物输出到 `autodrive_console/web-vue/`。主要页面为任务指挥台、实时运行观测、测试用例管理、场景前置配置、报告中心、运行配置和工具日志。

共享视觉样式集中在 `autodrive_console/web/*.css` 与 `frontend/src/*.css`。深/浅主题只写浏览器 Local Storage，不写机器人配置。新页面默认避免冗余说明文字，但必须保留必要的安全状态和错误反馈。

```bash
./run_vue_preview.sh
# 浏览器：http://127.0.0.1:5173
```

Vite 预览调用本机 `8087` API；页面导航必须保持在 `5173`，不能跳回后端端口。

## 11. 构建、发布与验证

### 构建

```bash
# 生成升级 ZIP
./make_upgrade.sh 1.18

# 同时生成首次安装 DEB
./make_upgrade.sh 1.18 --deb
```

版本号必须为数字点号格式。脚本会拒绝覆盖已有发布目录，并在 `releases/<版本>/` 输出 ZIP、`SHA256SUMS`、说明和可选 DEB。

### 每次改动后的最小验证集

```bash
python3 -m pytest -q tests/test_offline_modules.py tests/test_trajectory_integrity.py
python3 -m pytest -q tests/test_live_observation_realtime.py
npm --prefix frontend run build
node --check frontend/src/liveObservation.js
cmake --build build/live_preprocessor -j2
```

发布前仍需低风险实车验证：任务下发、Supervisor 阶段等待、方案应用/恢复、地图切换、报告下载、升级回滚和实时观测的移动/缩放表现。

## 12. 常见排障

| 现象 | 优先检查 |
| --- | --- |
| 服务可见却无法调用 | 普通账户的 ROS_DOMAIN_ID、RMW 环境、`/opt/ry/install/setup.bash`、`master_interfaces` 类型支持库。 |
| 重启节点后立即失败 | 编排是否等待每阶段全部 `RUNNING` 和稳定时间；方案应用后是否留出稳定窗口。 |
| 无点云或位姿 | Bridge 端口、预处理日志、TF `map → base_*`、点云 frame_id。 |
| 观测落后实车 | 是否回退到原始点云、预处理频率、浏览器性能、Wi-Fi；不要提高队列深度。 |
| 地图/墙体不对齐 | `/map` origin/resolution、map_server 当前 YAML、缓存 ID、实际墙体文件。 |
| 轨迹缺段 | map/TF 可用性、切图、坐标变换拒绝原因和报告中的证据提示。 |
| 升级后不能启动 | `updates/` 备份、`logs/ry-aletheia-error.log`、8087 端口占用、二进制权限。 |

## 13. 安全红线与维护准则

- 不使用 `sudo ./dist/ry-aletheia`；控制台应由普通账户运行。
- 受限 sudo 仅允许 `supervisorctl status/start/restart`，不得扩大为任意命令。
- 不覆盖机器人目标任务目录中已有的同名任务文件。
- 不将场景前置功能扩展为无约束的任意文件写入器。
- 不在 `running`、`cancelling`、`awaiting_recovery` 状态升级。
- 不以提高队列深度或保存历史帧换取“连续感”；实时性优先。
- 未经明确确认，不自动创建升级包、DEB 或部署到小车。

工程维护遵循：静态数据缓存、动态数据分层；高频路径限频/单槽队列/背压/超时丢弃；低频配置原子写入与备份；每次修改必须有编译、构建或回归测试，并定义缺地图、缺 TF、缺接口、端口冲突、权限不足等失败降级路径。
