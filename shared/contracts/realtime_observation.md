# 实时观测

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/telemetry.py`、`autodrive_console/observation.py`、`frontend/src/liveObservation.js` 和 `mobile/lib/features/live_observation/`
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

## 控制面 API

`GET /api/observation`、`GET /api/observation/active-map` 和 `GET /api/observation/maps/{id}/layers` 暴露活动地图、世界元数据、虚拟墙和遥测数据。当前会话生命周期使用 `POST /api/observation/start`、`/heartbeat` 和 `/stop`。

活动 OccupancyGrid 快照自身没有 `map_walls.yaml` 时，`layers` 仅可在该快照仍为活动地图、且 `/map_server` 当前 YAML 经分辨率、尺寸与原点严格核验一致时，使用该 YAML 同目录的虚拟墙；历史快照与未验证候选必须保持无墙，不能按几何相似性猜测或复用其他楼层的约束。

PC 已加载底图后可用同一份 `{ resolution, width, height, origin, frame_id }` 元数据调用 `POST /api/observation/live-layers` 补偿虚拟墙可见性窗口。仅当前地图 signature 可使用返回值；`matched: false` 不得被 Backend 负缓存，浏览器只能按单一有界计时器低频重试。补偿仅替换虚拟墙绘制层，不得重载底图纹理、重置视角或回放点云。

`GET /api/observation/localization-status` 是 PC 实时页使用的只读定位健康快照；它不下发重定位、Node Manager 或车辆控制命令。响应为：

```json
{
  "phase": "relocalizing",
  "label": "重定位中",
  "detail": "NDT 匹配质量低",
  "updated_at": 12345.67,
  "state_code": 4,
  "error_code": 100,
  "error_detail": "NDT 匹配质量低",
  "error_retained": false,
  "age_ms": 120
}
```

`phase` 的闭集为 `initializing`、`normal`、`warning`、`error`、`relocalizing` 与 `unavailable`。Backend 只读订阅既有 `/localization/status`（`master_interfaces/msg/LocalizationStatus`），将 `state`/`error_code` 转换为可读文本，并只公开已文档化的状态码、错误码及 `age_ms`：状态码为 0 初始化中、1 正常、2 WARNING、3 ERROR、4 重定位中；错误码为 0 无错误、100 NDT 匹配质量低、101 NDT 未收敛、200 LIO 漂移或快速运动检测、201 LIO 结果不可信、300 IMU 异常、301 雷达数据断流、400 定位内部异常。`error_retained=true` 表示实时 `state` 已恢复正常而诊断错误码仍由车端保留，不能把它渲染为新的错误状态。`fault_id` 是内部故障实例去重键，不公开也不得显示为错误码。接口由车辆运行时提供：该车未提供 `LocalizationStatus` 时，必须返回 `unavailable` 与“该车不支持实时定位状态”，不得暴露 Python 路径或原始异常。超过新鲜度窗口、其他 ROS 模块不可用或未收到首条状态时同样必须返回 `unavailable`，不得假定正常。一次重定位证据以同一非空 `fault_id` 首次进入 `state=4` 计数；它仅在自动测试运行中以已验证的地图坐标附到轨迹及离线报告，坐标不可验证时保留次数而不渲染地图标记。

当前消费者为 `robot_backend` 与 PC `web_console`；Mobile 不是该端点消费者。该接口是增量控制面 API，既有客户端可忽略。

## PC 手动重定位（受控）

PC 确认请求还携带 `request_id`（不超过 64 个 ASCII 字母、数字、下划线或连字符）；Backend apply 接纳后返回/保留 `operation_id` 与 `operation_outcome`（running/succeeded/failed）。旧请求省略 ID 保持兼容。Backend 有界记录最近 64 个请求的独立结果，重复 ID 不重放实际变更。`GET /api/observation/relocalization?request_id=…` 查询该请求，未接纳返回 `unknown`；`POST /api/observation/relocalization/resolve` 仅接受 `{request_id}`，原子地查询已接纳结果，或登记 `not_admitted` 并阻止该 ID 的延迟请求进入。resolve 不调用 ROS、不恢复驾驶、不重发操作，且不能被其它请求的 ROS 等待阻塞。HTTP 丢响应时 PC 只用匹配本次 ID 的结果解除提交不确定状态；unknown 必须经过 resolve 确认未接纳，不能从无关 idle/normal 快照推断成功或安全重试。本地预览在此期间仍可拖动。影响消费者为 Backend 与 PC Web；Mobile 不消费这些接口。

本地预览与机器人操作完全分离。地图可用时，PC 可随时直接拖动车体、右键调整朝向、找回图标和选择定位 YAML；idle、failed、unavailable、算法自动重定位以及本工具在途请求均不得禁止本地编辑。拖动、取消预览、关闭面板不发送 ROS/停车/恢复驾驶请求。确认入口捕获不可变的位姿、配置、源图与预览修订号，再按需调用 begin、等待真实停车确认并 apply；不要求操作者先点“保持停车重新对齐”。实际变更仍互斥，停车未确认绝不发定位服务。

PC apply 增量携带 `source_map_id`（显示底图的 16 位小写十六进制 ID）；Backend 对照 begin 直接 GetMap 绑定的实际栅格 ID，源图不符在任何 ROS 变更前拒绝。旧消费者省略字段保持兼容。begin/status 可返回同名源图 ID；不以活动地图缓存或 yaml_filename 替代真实栅格证据。现有 PC 地图仅支持平面无旋转原点，非单位/倾斜/旋转/非零高度原点必须明确拒绝实际提交。准备和初始化两阶段均在服务就绪后、紧贴发送前复核地图、运行实例、选中文件与停车。并发变更立即拒绝，不排队重放；状态读取不能因服务等待而长时间阻塞。

失败或状态接口中断保留用户预览；本次已提交快照不随继续拖动而改变，新预览不被旧成功回调、位姿交接或计时器清除。真实底图变化必须作废旧坐标并提示重设。切图已确认且目标图片已显示时，初始化失败只保留停车和失败提示，不锁住新图上的本地编辑。取消预览不恢复 navigation；恢复驾驶仍为独立的显式操作。影响消费者为 Backend 与 PC Web，Mobile 不消费本组接口。


人工介入不要求定位状态为 normal，也不要求实时位姿仍在发布：算法处于 initializing、relocalizing、error 或状态暂不可用时，仍可请求停车并手动指定地图位置与朝向。PC 提供整图视图与在地图上放置候选车体的入口；丢失/越界/不可见的实时车体不得阻塞编辑，缺少新鲜位姿时不显示无法对齐的动态点云和代价地图。候选是人工预览，不是实时定位结果。失败后 `/begin` 可重新建立停车占用、重新核验当前地图和定位进程，再进入对齐；不得要求先切回 navigation。仍禁止与本工具在途请求、手动驾驶会话或地图标记导航并发。停车未确认时不能提交；失败保持停车，本次服务后定位完成确认规则不变。

一键找回进入本地放置模式：车体预览跟随地图上的鼠标，地图区域隐藏指针，点击落位、按住拖动设置朝向；落位前不能提交。取消找回或 Esc 恢复找回前的候选，不发送服务。大地图中的预览图标保留至少 32px 长度便于辨认，真实车体观测继续使用车辆模型的米制比例；放大预览图标不改变候选坐标、点云变换或服务位姿。此增量消费者为 Backend（失败后的停车重试）和 PC Web（独立于实时位姿的放置、整图和重试入口）；HTTP 请求/字段与 ROS 服务格式不变。Mobile 不消费手动重定位端点，无需 Mobile 工具链检查。验证包含自动重定位卡住、无实时位姿、地图外车体、旋转/缩放下位置及航向、失败停车重试、控制源丢失重新确认和重复请求互斥。

停车切换期间允许原控制源的反馈继续到达，只有实际 `miniapp` 确认才允许发送重定位服务，本地编辑不等待停车确认，且原 4 秒切源时限不因反馈延长。停车占用失效须立即禁止实际提交并进入受控失败，本地预览保持可编辑；`vehicle_source` 反映真实回报，不能因失败保持记录而伪造为 miniapp。地图读取复用 Backend 自有节点与独立 executor，首个查询超时允许一次有界只读重查。`yaml_filename` 仅作初始路径提示，Nav2 LoadMap 不保证更新该参数；每次操作以 `/map_server/map`（`nav_msgs/srv/GetMap`）的真实栅格绑定地图，后续以元数据及完整栅格摘要检测地图变化，不使用地图缓存、不重试任何实际重定位请求。失败说明显示已登记的受控原因，不暴露原始异常。

PC 提交、开始、取消、恢复请求均单次在途；旧轮询响应不得覆盖新动作结果。校准使用原始 map 位姿，禁止用预测或平滑后的显示坐标生成服务位姿；车体、点云、代价地图使用一致的 `T_target * inverse(T_live)` 预览变换，最新数据变化不能覆盖操作者的目标。移位保持鼠标抓取偏移，转向保持相对角度；仅冻结本次已提交快照；本地新预览仍可编辑，并以修订号区分。成功响应后以新到达的真实位姿接管显示，清理旧预测状态及旧地图层，不能先退回提交前的显示位姿，也不能把目标伪造为实际定位结果；无新反馈时明确显示等待，不保持伪造的实时车体。

PC `web_console` 消费下列受控端点；动作请求仍为 JSON `POST`：

| 端点 | 请求 | 语义 |
| --- | --- | --- |
| `/api/observation/relocalization/begin` | `{}` | 请求并确认车辆切至 `miniapp`、发布 STOP；PC 在确认流程内部调用，停车确认后才能发送重定位服务。 |
| `/api/observation/relocalization/apply` | `{ "x": number, "y": number, "yaw": number, "source_map_id"?: string, "request_id"?: string }` | 仅接受有限地图坐标与航向；Backend 以同一受控地图与该位姿执行两阶段 ROS2 调用。第二阶段的“已接受”不是完成：必须在本次初始化请求的状态游标之后观察到 `/localization/status` 的 `initializing` 或 `relocalizing`，随后收到新鲜的 `normal`，才请求恢复 `navigation`。 |
| `/api/observation/relocalization/cancel` | `{}` | 旧客户端兼容：尚未提交时请求恢复 `navigation`；新 PC 取消预览不调用该端点。 |
| `/api/observation/relocalization/recover-navigation` | `{}` | 服务失败或超时后由操作员显式恢复 `navigation`。 |
| `GET /api/observation/relocalization/configs?path=…` | 无 | 只读浏览 `/opt/ry/config/localization` 内一层目录；省略 path 从根目录开始，返回 root/path/parent/directories/files，仅列出 YAML/YML 文件，不返回正文。 |

请求体上限 16 KiB。`/apply` 允许额外的可选字符串 `config_path`：省略或空字符串表示自动沿用；非空表示用户本次从受控定位目录选择的 YAML。浏览器仍不得指定底层 `map_path`、服务名、`z`、roll、pitch、轮速里程计开关或 ROS 原始错误；Backend 独立校验选择后生成 ROS 请求。响应包含阶段、可读说明、`can_begin`、`can_apply`、`can_cancel`、`can_recover_navigation` 与当前控制源；手选加载成功后可附带 `target_map_id`，它是既有 OccupancyGrid 缓存规则计算的 16 位运行时地图 ID，供 PC 等待该地图的真实底图，旧消费者可忽略。阶段为 `idle`、`switching_to_miniapp`、`calibrating`、`calling_service`、`switching_to_navigation` 或 `failed`。`calling_service` 中车辆必须继续保持 `miniapp` 停车；若服务未明确确认、定位状态未完成上述状态转换或确认超时，必须转为 `failed`，不得恢复自动驾驶。

默认自动模式不读取定位 YAML，两阶段请求固定 `map_path=""`，由已核验的定位节点沿用切图后当前持有的配置。手选模式只接受受控定位目录内存在、可读、有界大小的 `.yaml/.yml` 常规文件，解析其 `system.map_path` 并确认它是存在的绝对地图目录；允许用户主动选择与当前二维地图不同的定位地图，缺字段或格式无效则在发服务前拒绝，保留对齐状态供用户重新选择。两阶段传相同的已验证规范文件路径；初始化实际发送前再次核对文件身份和内容，期间变化则保持停车。手选模式执行二维切图与定位初始化，只有两者均确认才恢复 navigation。两种模式都不生成副本、不改写 YAML 或启动脚本，本次 `x/y/z/roll/pitch/yaw` 仍明确由服务请求传入。手选模式会让定位节点加载整份所选配置，确认提示必须显示所选文件；选择仅用于本次，每次开始重定位默认自动，不在浏览器或 Backend 持久化。行为树和启动脚本的路径可用于只读诊断，但不证明节点切图后的当前配置，也不作为自动模式的配置选择来源。

当前已核验的运行版本为 Lightning `1.6.5+compatible.5`；以供应商包与实车一致的程序/库 SHA-256、唯一同 ROS 域运行进程、实际加载库的设备号和 inode 共同确认空路径协议能力。自动空路径调用在未知版本、升级后尚未重启、库内容不一致、多定位进程或无法读取运行证据时必须拒绝，不能仅凭包版本推断能力；显式 YAML 模式不要求空路径能力，但仍必须绑定并复核唯一运行进程；新增构建必须经过接口和实车运行证据核验再登记。确认流程建立停车占用时绑定实际地图和定位进程启动身份；提交前、两阶段之间、定位完成后重新核验进程身份，等待定位确认期间定期核验地图。自动模式只允许原地图；手选模式从 `system.map_path/map.yaml` 确定目标二维地图，目标必须位于受控地图根目录且文件有效。准备阶段确认后，Backend 并行调用 `/map_server/load_map`（`nav2_msgs/srv/LoadMap`）与定位初始化，实际变更服务均只发送一次。并行期间允许受控地图变化，确认屏障之后任何实际栅格变化均拒绝；切图返回成功后必须以新 GetMap 响应与 LoadMap 返回栅格逐项/完整摘要核对，不依赖 yaml_filename 更新；最终严格绑定目标地图并等待本次定位正常。切图不成功、参数仍是旧图或定位失败均保持停车，不自动回滚地图。地图查询失败、无关切图或定位进程重启必须保持停车，不能自动退回启动配置或其他 YAML。

本次影响：Backend 增加受控只读定位配置浏览与校验、并行二维切图与定位初始化，PC Web 增量提交 `config_path` 并提供本次配置选择。旧请求省略字段仍保持自动模式；Mobile 不是消费者，无受影响 Mobile 检查。需验证目录逃逸、跨地图配置加载与二维切图确认、两分支并行与单侧失败保持停车、无关切图拒绝、文件变化拒绝、选择重置、浏览失败可回自动、请求在途锁定及既有停车和完成确认。手选请求期间 PC 隐藏旧底图并丢弃位姿/动态层；LoadMap 派生的 target_map_id 底图真正加载完成后才允许位姿交接。缓存/图片失败时明确等待并重试，不把目标位姿画在旧图上；实际地图缓存标记尚未同步前拒绝旧 ID 回退，同步后仍响应后续真实切图。验证范围为 Backend 默认模式不读取定位 YAML、手选模式只读验证配置、沿用运行配置、未知/陈旧运行版本拒绝、切图/重启拒绝、两阶段调用及定位完成确认；实车只读核验不等于实车重定位成功。

手工 Service 初始化可报告状态 0（`initializing`），不等同于自动故障恢复的状态 4。Backend 为手工完成确认保留独立、有界的状态记录：记录初始化/重定位样本和状态变化，与 `fault_id` 无关，避免短暂状态在 HTTP 线程开始等待前消失。第二阶段的状态游标必须在服务就绪、地图及运行身份核验完成后，紧贴实际发送请求前取得；服务发现等待或核验期间的旧初始化记录、一直维持的正常状态都不能作为本次完成证据。既有故障事件清单仍仅按非空 `fault_id` 去重，轨迹及报告中的自动故障恢复次数不能因手工初始化而增加。

手动重定位预览只存在于 PC 地图：候选车体位姿对 map 坐标系中的点云及局部代价地图施加同一刚体变换，静态地图、格栅、比例尺与虚拟墙不得移动；取消或底图变化时清理预览，失败时保留；提交仅冻结已确认快照，成功后等待新实时位姿再交接显示。浏览器只在候选 `x`、`y`、`yaw` 都为有限数时才允许提交，并在请求在途期间锁定提交动作；失败说明必须保留到操作者下一次操作，不能被状态轮询静默覆盖。工具日志以 `manual_relocalization` 来源记录 ROS 域、两阶段服务确认、定位状态确认和受控失败原因；不得记录地图绝对路径、原始服务报文或原始异常。实时遥测仍使用 latest-wins，不得因手动重定位把旧点云或旧位姿回放给操作者。Mobile 不是本组端点消费者，也不得展示入口。

## PC 手动地图标记与受控前往

PC `web_console` 使用手动地图标记，不读取、遍历或解析任何任务文件。Backend 仅在 map_server YAML 与当前 OccupancyGrid 的分辨率、尺寸和原点严格匹配后，使用其内部活动地图资产身份筛选和保存标记；该身份、地图路径和 ROS 参数均不会出现在浏览器请求或响应中。地图未确认时，`GET /api/observation/map-markers` 返回 `{ "map_ready": false, "points": [] }`。

| 端点 | 请求 | 语义 |
| --- | --- | --- |
| `GET /api/observation/map-markers` | 无 | 返回当前已确认地图的 `{ "map_ready": true, "points": [{"id","alias","x","y","yaw"}] }`。 |
| `POST /api/observation/map-markers` | `{ "alias": string, "x": number, "y": number, "yaw": number }` | 在当前已确认地图创建一个持久化标记。 |
| `POST /api/observation/map-markers/remove` | `{ "id": "opaque-id" }` | 仅删除当前已确认地图拥有的标记。 |
| `GET /api/observation/map-marker-navigation` | 无 | 返回受控前往状态。 |
| `POST /api/observation/map-marker-navigation/begin` | `{ "id": "opaque-id" }` | 后端重新核验当前地图、标记归属与车辆安全状态后创建 Nav2 目标。 |
| `POST /api/observation/map-marker-navigation/cancel` | `{}` | 仅请求取消当前控制器拥有的 Nav2 目标。 |

标记只由工具配置 `config/live_map_markers.json` 持久化；每项含不透明 ID、操作员别名和有限 `x/y/yaw`。别名去首尾空白后为 1–48 字符，坐标绝对值不超过 100,000 米，yaw 输入为弧度且保存为 `[-π, π)`；每张地图最多 500 个。写入使用临时文件、`fsync` 和原子替换。浏览器不能提交内部地图身份、地图路径、Action 名称、速度、行为树或任意 ROS 参数。

请求体上限 16 KiB。开始前和提交 Nav2 Goal 前，Backend 都必须重新确认当前地图的 map_server YAML 与 OccupancyGrid，并确认标记仍属于该图；任一信息缺失、过期或不一致均以 HTTP 409 拒绝，绝不自动切图、跨楼层或过电梯。ROS Action 不可用时返回 HTTP 503。

一次操作最多运行 **300 秒**。`accepted` 不是到达成功，只有 Nav2 最终成功结果才进入 `succeeded`；拒绝、失败、取消、超时或安全状态丢失必须请求取消现有 Goal 并返回受控失败信息，不能重试、发布 Twist 或切换控制源。取消只使用当前 Goal 的 Nav2 cancel 流程。

Backend 自己每 **200 ms** 复核同图、定位、急停、真实控制源、手动/重定位占用和时限；浏览器轮询、页面关闭或断网不影响该循环。状态 `checking`、`navigating`、`cancelling` 与 `cancellation_unconfirmed` 均保持运行与手动控制互锁。后者表示已请求取消但尚未收到 Nav2 终态确认：`can_begin` 与 `can_cancel` 都为 false，只有终态回调才可解除互锁。工具日志只记录标记 ID、地图匹配、目标接受/终态、取消及安全拒绝，不记录别名、坐标、路径或 ROS 消息。

地图标记导航进行时，`GET /api/observation/map-marker-navigation` 可增量返回 `route: null` 或 `{ "frame_id": "map", "points": [{"x": number, "y": number}] }`。路线仅由 Backend 的唯一 Nav2 worker 只读订阅 `/plan`（`nav_msgs/msg/Path`）：只接受 `map` frame、有限二维点且终点与当前受控 Goal 相符的路径，抽稀后最多 512 个点。终态、取消、失效安全条件、切图和新 Goal 都必须清除路线；浏览器的图层开关只能隐藏绘制，不能改变订阅、Goal、互锁或取消。

PC 实时页消费受控路线数据，并以默认开启的“规划路线”图层在虚拟墙之后、地图标记之前绘制；Web 不得访问 ROS 或推测其它导航客户端的路线。Mobile 不消费或展示路线数据，也不是这些端点消费者。

## 实时传输

机器人侧预处理器以 `RALT` 格式发送本机接入的 UDP 帧。网关在端口 **8768** 暴露二进制 WebSocket 通道：

| 通道 | 路径 | UDP 接入端口 | 记录载荷 |
| --- | --- | --- | --- |
| `cloud` | `/cloud` | `8769` | XY 浮点数对，最多 3000 个点 |
| `pose` | `/pose` | `8770` | 单条 X/Y/yaw 浮点记录 |
| `costmap` | `/costmap` | `8771` | map 坐标系栅格原点、分辨率、宽高及最多 65,535 个 OccupancyGrid 原始 cell；PC Web 与 Flutter Mobile 消费 |

浏览器和 Mobile 载荷以 **ALTM v1** 开头。消费者必须在渲染前验证魔数、版本、通道类型、记录数、声明载荷长度和有限数值。`costmap` 使用 `kind=3`，payload 以网络字节序 `float32 map_origin_x/y/yaw/resolution`、`uint16 width/height` 开头，随后为 `width × height` 个原始 unsigned cell。ROS `OccupancyGrid.data` 的 `-1` 按其原始字节值传输为 `255`；浏览器必须把未知值视为不可绘制区域，而不能误当作致命障碍物。

## 时效与渲染

所有阶段均为 latest-wins：每个来源只保留一帧待处理数据，不确认、不重传，过期帧直接丢弃而非回放。`costmap` 的 C++ 预处理必须先拒绝默认 5 秒之外的 ROS `header.stamp`（包括晚启动收到的旧锁存图），再按该时间戳将其 `header.frame_id` 和 `info.origin` 投影到 `map`；消费者只显示已经在 map 坐标系中的栅格，不能默认 `odom == map` 或以最新 TF 猜测旧栅格位置。唯一受限兼容是新鲜 `odom` 栅格的精确时间查询失败时：只有最新 `map ← odom` 经完整 3D 单位变换校验后才可使用；非单位变换、其它 source frame 或查询失败必须丢弃。PC 与 Flutter Mobile 都将未知/自由 cell（`255` / `0`）透明绘制，使用同一分段色标，并在本地接收超过 5 秒、切图或无有效后继帧时安全隐藏。地图图像、格栅、局部代价地图、虚拟墙、PC 地图标记、点云、位姿和车辆指示器共享同一个世界坐标到屏幕坐标变换；PC 固定图层顺序为底图 → 格栅 → costmap → 虚拟墙 → 地图标记 → 点云 → 车体，Mobile 不绘制地图标记。地图保持北向/原始地图朝向，仅车辆旋转。

## Planned（规划中）

尚未批准通用遥测总线。新增实时数据必须使用独立版本化通道，并明确有界内存与时效行为。
