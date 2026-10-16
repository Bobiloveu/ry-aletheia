# NVENC 视频带宽源码分析与候选方案（本地验证，待实车）

当前范围：用户要求先完成源码分析，后续再上实车验证。已补齐本地分层统计与显式 VBR 候选，默认 CBR 和用户运行配置不变。候选尚无 GA107 实测，不能认为已经缩小实车带宽差异。目标是保持配置的分辨率、帧率和码率预算，验证是否可降低简单画面编码流量与发送突发。

边界：仅本地开发和测试；用户确认新车不在现场。不连接车辆、不调整网络限速、不打包或部署，不把软件编码对照说成 GA107 实测。

已确认：老车 `video-runtime (1).log` 的 12 条六路采样为 1.499–1.856 Mbps；新车 `video-runtime.log` 为 6.588–80.299 Mbps。VAAPI 1.20.1 默认 CQP，会清除非目标码率模式的内部 bitrate；NVENC 1.20.3 显式 CBR，配置合计 6.5536 Mbps。CBR 下 max-bitrate 无效。80 Mbps 的放大层尚无同期原始编码计数证明。

实施与后续验证：

- [x] 补齐回环 MediaMTX paths 输入计数、每观看端期望发送量与近似输出倍率；源重启/缺失/错误独立重建基线，不能伪报重传结论。缺失/未就绪源不能冒充完整编码总量，窗口错位或查询耗时超过采样间隔的 1% 时倍率未知。
- [ ] 评估 NVENC 的受限 VBR 与画质目标：保留 bitrate/fps/resolution、baseline、无 B 帧与原启动时间轴，保留 CBR 回退，VAAPI 不变。CQ 23、strict-gop、三帧 VBV 只是待独立对照的参数候选，不能同时修改后归因；不能承诺同等画质或限制任意瞬时线速。硬件预检与真实管线若调整，必须保持一致。
- [x] 先观察缺口测试失败，再实现；覆盖配置/参数、冻结选择、计数身份、源失效、窗口错位、日志限频、期限、停止与故障隔离。
- [ ] GA107 上用同源画面对照固定码率与 VBR 候选的流量、帧数、画质和延迟；本机无 NVIDIA GPU，软件替代编码不能证明该目标，因此不以其代替验收。
- [x] 执行相关 Backend、离线、C++/ROS 编译检查和独立只读评审，记录结果与硬件验收缺口。

协议影响：Backend/native 执行，Web/Mobile 继续消费相同 H.264/WHEP 和状态枚举；仅增量诊断字段，不需要客户端改动或 Flutter 工具链。

源码复核结论：

- `live_preprocessor/src/video_pipeline.cpp:59`：VAAPI 仅设置 bitrate 与 keyframe-period，未覆盖 rate-control；锁定上游 1.20.1 默认 CQP，非目标码率模式在 ensure_bitrate 中将内部 bitrate 清零。不能把该配置视为实际 CBR 上限。
- 同文件 NVENC 分支显式 `rc-mode=cbr`，上游 1.20.3 以 bitrate×1024 设置平均目标；六路配置合计 6.5536 Mbps，接近日志 6.588 Mbps。固定质量与固定码率策略差异能解释基础差距，不能单独解释 80.299 Mbps 的五秒窗口。
- `max-bitrate` 上游明确说明 CBR 下忽略；VBV 默认 0 表示使用驱动预设，不能说成无限缓存。CQ、strict-gop、小 VBV 的实际效果必须硬件验证，小 VBV 可能损害关键帧质量。
- ROS 与 ShmSDK 使用相同输出预算与 latest-slot；单帧 GStreamer 队列丢弃旧帧。源码未发现 NVENC 专属的补发历史帧或加倍 FPS 逻辑。新车输入 JPEG 会在本机解码后重新编码 H.264，不直接向浏览器传 JPEG。
- `autodrive_console/video_bandwidth.py` 统计的是 WebRTC 会话累计发送字节差，不是编码器原始 H.264 输出。已有身份变化、计数回退与单调时钟保护；当前日志缺少同期源输入计数，无法排除编码输出异常、传输重发或计数边界问题。
- 下一次实车应同步对比编码输入、观看连接数、WebRTC 输出与网卡发送，并用相同画面分别测每个参数；不同车辆、不同原始格式和场景的日志不能证明画质效率等价。

本地候选的实际边界：

- `runtime.nvenc_rate_control` 仅接受 `cbr` / `vbr`，省略默认 CBR；不改配置模板、不迁移配置、不自动启用候选。
- VBR 设置原 bitrate、同值 max-bitrate、const-quality=23；保留低延迟 preset、无 B 帧、zerolatency、原 GOP、baseline 与双 identity 时间轴修复。strict-gop / VBV 暂不叠加，以便实车单变量归因。不能承诺 CQ23 与 CBR/Intel CQP 同画质。
- NVENC 预检、选择缓存与 native 使用同一模式；当次运行冻结已预检策略，后续配置修改在下次运行生效。VAAPI 参数不变。

本地验证记录：

- 新增候选策略的三项 Python 用例先失败，再实现；C++ 新用例先因缺少策略能力失败，再实现。
- 分层统计新增正例、多观看端、源身份/计数/上线时间变化、源失败恢复、源分页、源请求总期限；独立评审发现的部分总量与错位窗口均先补失败复现，再修复。
- `env -u PYTHONPATH pixi run python -m pytest -q tests/test_video_bandwidth.py tests/test_video_runtime.py`：66 通过。
- `env -u PYTHONPATH pixi run test-offline`：109 通过（已有 TestCase 收集警告）。
- `pixi run cmake --build build/live_preprocessor --target aletheia_video_frames_test aletheia_video_ingest --parallel 2` 编译通过；CTests `video_frames/video_io` 2/2 通过。
- `scripts/doctor.sh --profile backend` 通过；没有为 Backend 引入 Flutter 或 Android/iOS 工具链。
- 离线回放此前保存的九个实车采样，首末相隔 8.0464 秒，复算编码输入 6.61708 Mbps、WebRTC 发送 6.86319 Mbps，倍率 1.03719，与之前独立测量一致。它验证统计口径，不能证明 VBR 候选效果。
- 独立只读复核：两项 P2 边界问题已闭合，新边界用例 3/3 通过，未发现新阻断。

未完成的目标证据：新车缺席且本机无 NVIDIA GPU，尚未运行 VBR 候选，尚未证明原 80.299 Mbps 异常的放大层，也未证明优化后的 GA107 带宽、画质、时延与资源占用。目标保持未完成；不打包、部署、提交或推送。
