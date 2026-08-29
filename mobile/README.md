# Aletheia Mobile

Aletheia 的 Flutter 移动端专业 HMI（Mobile Robot HMI / Test & Diagnostic
Console），面向与机器人处于同一可信局域网的机器人运行、测试与诊断人员。
它将机器人状态监控、实时可视化、测试诊断和测试任务管理组织为统一入口。

## 开发与维护文档

- [协作约束（AGENTS.md）](AGENTS.md)：人类维护者与多 Agent 的阅读顺序、边界、文件所有权和交接规则。
- [架构手册](docs/ARCHITECTURE.md)：路由、Provider、网络、实时地图/视频、平台与安全边界。
- [开发工作流](docs/DEVELOPMENT_WORKFLOW.md)：运行、Gallery、测试、构建、真机检查和故障排查。
- [文档中心](docs/README.md)：按维护角色索引所有 App 文档。
- [设计系统](docs/DESIGN_SYSTEM.md) 与 [UI Spec](../docs/UI_SPEC.md)：视觉与页面职责。
- [最新开发断点](../docs/AI_CONTINUATION.md)：继续当前工作前的上下文恢复记录。

## 品牌资源

应用内 Logo 直接渲染 `assets/branding/aletheia_icon_vector.svg`。系统桌面图标必须使用同一 SVG 导出，执行 `./tool/regenerate_launcher_icons.sh` 后会生成 iOS AppIcon 目录和 Android legacy / Adaptive Icon 资源；生成的 PNG 只用于平台要求，不作为第二份可编辑设计源。

## 一级导航

- **首页**：连接、状态确认与车端健康概览。它是进入当前机器人 HMI 的起点，不改变“连接机器人”这一具体操作。
- **观测**：地图、Pose、PointCloud 与按需相机工作区。
- **工具**：当前包含自动化测试、用例库、测试报告、诊断日志、运行配置、场景前置配置与控制台服务；它们都属于当前机器人的二级能力。
- **设置**：手机本地语言、HMI 显示、版本信息、App 更新检查与问题反馈；不依赖机器人连接，也不会改写车端配置。HMI 显示默认是深色，也提供高对比深色与低反光日间模式；三者不改变地图、视频或状态数据语义。问题反馈提供描述、联系方式、截图与 App 诊断摘要/本次会话日志选择；当前开发版本只进行本地校验，未来上传由独立接口实现。App 更新与机器人离线升级目录严格隔离。

当前完成 Phase 1：

- 输入并保存机器人主机地址，固定访问现有 HTTP 控制台 `:8087`。
- 读取 `GET /api/observation`，展示控制台、遥测、预处理与地图缓存状态。
- 仅在用户明确操作且车端已启用时调用实时观测启动接口；App 在后台暂停心跳，车端按现有空闲策略回收资源。
- 支持 IPv4、主机名与括号包裹的 IPv6 地址。

当前也完成 Phase 2：

- 读取车端用例库与任务文件校验提示；移动端不改写 `tasks/`。
- 从选定用例创建测试计划，并在提交前明确展示轮次与间隔。
- 仅在运行处于活动状态时以 1 秒间隔读取 `/api/runs/latest`。
- 显示预检、Supervisor 快照、轮次结果、轨迹证据入口、停滞处置、人工恢复与终止剩余轮次流程；所有会改变测试状态的动作均要求显式确认。
- 用例库支持既有的 JSON / `.rycase.zip` 导入、受控导出、别名、版本、生命周期、标签、说明和场景绑定；只发送用户明确选择的文件内容。
- 运行配置、场景前置配置、报告下载/删除、诊断文件下载和控制台安全停止均复用既有车端 API；场景应用/恢复、删除报告与退出控制台均先要求确认。
- 场景文件浏览支持读取受控目录内的文本预览、大小和 SHA-256 摘要，再选择文件；App 不提供任意路径读取或写入。
- 应用设置只保存到当前手机：可选择简体中文或 English 偏好、默认 HMI 深色 / 日间模式 / 高对比深色显示，查看版本和检查 App 更新，并在 App 内填写问题与建议。它不会修改机器人运行配置；英文页面按迁移逐步扩展。

当前也完成 Phase 3：

- 观测页读取活动地图的既有缓存元数据、PNG 预览和虚拟墙；墙体沿用车端 `world` / `image_relative` 坐标语义。
- 地图车体轮廓读取既有 `/api/settings` 的 active vehicle model，以长度、宽度、地图分辨率和当前缩放真实投影；设置暂不可用时才使用与 PC 控制台一致的回退尺寸。
- 车端已启用实时观测时，进入观测页会调用既有受控启动接口，并只订阅 `ws://<host>:8768/pose` 的 `ALTM` v1 二进制位姿通道。
- 严格校验帧魔数、版本、流类型、记录数和 3 个大端 `float32` 位姿值；断线时指数退避重连，不请求历史帧。
- 位姿覆盖层独立于地图加载与交互。后续 PointCloud、Trajectory 等图层可并列接入，不需要改写地图容器。

当前也完成 Phase 4：

- 只订阅独立的 `ws://<host>:8768/cloud` 二进制点云通道；严格验证 `ALTM` v1、最多 3000 组网络序 `float32 x/y` 记录与有限坐标。
- WebSocket 客户端只保留一个尚未消费的帧，并在 Flutter 下一渲染帧解码；超过 100ms 的帧直接丢弃，不追赶历史画面。
- 点云通过独立 `CustomPainter` 直接消费 packed `Float32List` 绘制，避免每帧创建 `Offset` 列表；静态地图、虚拟墙、点云与车体各自位于 `RepaintBoundary`，缩放和平移仍由同一个地图 viewport 统一处理。
- Pose 与 PointCloud 都只保留最新未消费帧。Pose 超过 250ms、PointCloud 超过 100ms 的本地待处理帧直接丢弃，不追赶历史画面。
- 每 5 秒随有效点云帧向既有 `client-metrics` 接口低频回报点云包频率与源时间年龄；诊断上报失败不会影响观测。

当前也完成 Phase 5：

- 相机工作区读取 `GET /api/video/status` 的全部已配置流，并且只通过既有受限的流名开关调用 `POST /api/video/control`；不会提交 ROS topic、路径、命令或硬件参数。
- 操作者可独立启停已配置流并切换主画面。默认优先 `front_camera`，未配置时回退到车端第一条流；空间充足的横屏相机工作区最多同时显示三路真实 WHEP 画面（主画面加两路辅助画面），竖屏仍只显示主画面。进程内全局解码上限固定为三路，第四路会等待既有 renderer/session 释放，绝不无上限解码全部六路。
- 使用 `flutter_webrtc` 建立 receive-only WHEP 会话：发送 SDP offer、应用车端 SDP answer、显示原生 `RTCVideoRenderer`，退出相机工作区或应用进入后台即关闭 PeerConnection、删除 WHEP session 并释放 renderer。
- 地图与相机是独立工作区：相机视图不构建地图/点云/Pose 覆盖层，地图视图不构建 WebRTC 播放器，避免移动端同时承受两条高频渲染路径。

当前版本已将网页端现有的监控、观测、测试、用例、场景、报告、日志、运行配置与控制台服务能力适配到移动端。离线升级 ZIP 是唯一明确排除的网页能力，必须通过电脑端流程完成。App 不提供底盘、导航或 ROS 直接操作；未来 Robot Operation / Command 必须使用独立的命令契约、权限和审计路径，不能复用观测链路。

## 本地运行

```sh
flutter pub get
flutter run
```

## 网络边界

当前机器人服务为明文 HTTP/WS，且地址由操作员输入。为支持这一既有部署，Android 启用了 `INTERNET`、网络状态权限和明文流量；iOS 声明了本地网络用途并允许现有 HTTP 连接。仅可在可信局域网中使用。生产发布前应优先让车端提供 TLS 与认证，再收窄平台网络策略。

## 验证

```sh
flutter analyze
dart test -r expanded
flutter build ios --simulator --debug --no-codesign
flutter build apk --debug
```
