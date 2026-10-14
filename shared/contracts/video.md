# 视频

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/video.py`、`web_console.py`、`frontend/src/liveObservation.js` 和 `mobile/lib/features/live_observation/`
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

`GET /api/video/status` 返回已配置的视频流和运行时健康状态。`POST /api/video/control` 是客户端控制全局或单路启用状态的唯一入口。客户端必须使用返回的已配置流名称，不能自行拼接相机端点。

实际视频像素通过媒体网关到浏览器或 Mobile 的只接收 WHEP/WebRTC 会话传输。Python 只管理配置、进程生命周期和健康状态，不转发视频帧。离开视频工作区、切换流、App 进入后台或销毁视图时，必须释放对应会话、PeerConnection、媒体流和 renderer。

## 2026-10-13 兼容性增量与消费者影响

**Status: Existing（已实现并通过本地回归；实车 GPU/端到端性能尚待验收）**

- 运行执行方：Backend 管理受控硬件编码能力、逐路进程恢复与状态；C++ 仅旁路读取明确指定的 ROS Image 或 ShmSDK Cam 通道；不猜测切换源。
- Existing 消费者：Desktop Web、移动 Web 与 Flutter Mobile。原 `enabled/gateway/streams` 字段、`online/waiting/offline/disabled` 状态、已配置流名和 H.264 WHEP URL 保持兼容。增量 `runtime` 诊断包含状态/选择编码器/错误说明；客户端忽略未知字段仍可读取原状态。
- 增量诊断结构：`runtime={state:disabled|starting|ready|error, encoder:vaapih264enc|nvh264enc|null, device:string|null, error_code:string|null, detail:string}`；每路可增加 `error_code/detail/retry_count`。这些字段均可缺省，旧客户端不能因未知字段或未提供增量字段而拒绝响应。
- 车辆配置 `runtime.encoder` 增量允许 `auto/vaapih264enc/nvh264enc`。auto 先验证已有 Intel VAAPI 路径，再验证 NVIDIA NVENC；不自动采用软件编码。探测仅在显式启用视频时进行，并有期限/结果缓存。旧缺省 Intel 设置通过 `hardware_selection_version=1` 只迁移一次，之后保留明确硬件选择。`vaapi_device` 可为 auto 或受限 `/dev/dri/renderD数字` 路径，不成为浏览器文件访问接口。
- native `--encoder` 为受控 Backend 选择的 VAAPI/NVENC；旧缺省调用仍允许 VAAPI。帧继续通过本机 fd 交给原生编码器，不经 HTTP/Python；输出 resolution/fps/bitrate 预算保持。
- 输入兼容增量处理 JPEG/JPG/MJPEG、RGB/BGR 别名、常见单/四通道及明确排列的 YUV422；JPEG 以受限内容头校验，raw 以实际尺寸/stride/长度校验。新鲜帧只保留最新槽，限帧后才做昂贵解码。
- 一路输入异常只重试该路，退避有界且不重启其它路/MediaMTX；正常停用不重试。无可用硬件编码器明确报错，不能把网关 API 在线当作编码可用。
- Web 必须通过实际解码首帧判定播放，设置 WHEP/首帧期限并正确释放过时会话。Flutter 原 HTTP 期限与过时响应清理保持；本次不改变其原字段/枚举，验证其现有解析兼容增量状态。
- 验证影响：Backend/native 格式、硬件选择、隔离恢复、打包依赖；Web 生命周期与诊断；Mobile 定向既有视频解析/WHEP 消费检查，原 API 不引入新强制字段。本机 Mobile 仅完成既有解析的静态兼容核对，Flutter 工具链未安装，未声称移动端真机验收。

## 2026-10-14 冷启动与恢复影响

消费者为 Backend、Web、Mobile；原 API 字段与枚举保持兼容，无新增客户端必填字段。
NVENC 预检最多十秒、可取消；VAAPI 保留四秒。NVENC 各输入进程依次启动，上一流发布 H.264
或十二秒等待到期后才启动下一路，缺失输入不能永久阻断其他路；启动结束后不增加持续轮询。
原生编码管线保留总计十秒的初始化写入窗口，不能把第一次成功写管道当作编码初始化完成；
窗口结束后保留 250 毫秒背压期限。管线失败后按 1/2/4/8/16/30 秒退避，只影响该路；
连续成功提交满六十秒才重置退避。始终只保留最新输入，不积压历史帧，不自动软件编码。
日志区分创建进程、输入到达、编码提交失败；GStreamer 警告进入既有视频日志。
验证范围为 Backend/native 生命周期、超时与取消；Web/Mobile 原消费字段不变，无新平台依赖。
这些保护不等同于确认现场驱动阻塞根因或完成新车验收。

## 2026-10-14 NVENC 时间轴衔接

本次影响仅为 Backend 拥有的原生视频管线；Web/Mobile 的 H.264、WHEP URL、状态字段、
分辨率、帧率与码率均不变，无客户端代码或新平台检查依赖。

保留 `fdsrc do-timestamp=true` 的实际输入时间轴。NVENC 管线在 `rawvideoparse` 后、原有队列前，
先以 `identity sync=true` 等待 PLAYING，再由独立的 `identity drop-buffer-flags=discont` 丢弃
启动时可能没有有效时间戳的完整首帧，避免首个 segment 未偏移、后续帧才应用 NVENC 偏移，
使 RTSP 发布器等待远未来帧。两步不可合并：同一 identity 会先执行丢弃而跳过同步。
VAAPI 参数保持不变；仍只有编码前的单帧 latest-wins 队列，不增加历史缓冲。
验证必须覆盖并发启动、首个编码输入的有效且接近运行时间的 PTS、持续媒体字节增长、
实际 WHEP 解码及短暂断流恢复后的抖动缓冲，单次 ready 或首帧不足。

## 2026-10-14 私有 RTSP 端口冲突

影响范围为 Backend 拥有的 MediaMTX 和原生发布器；Web/Mobile 的 API、WHEP 地址与视频预算
均不变，不新增客户端依赖。启动私有网关时，优先使用配置的回环 RTSP 端口；若已被占用，
只为本次运行选择空闲回环端口，同时用于网关监听和所有原生发布器。运行中单路启停、重试
仍沿用本次选定端口，不能被重新读取的原始配置覆盖。

不得停止或修改占用端口的外部服务，不回写用户 `config/video.json`，不迁移对外 WHEP/API
端口。候选耗尽或非占用类 socket 错误应明确失败，不无限重试。端口检查是本机 bind 检查，
不向机器人已有服务发送探测连接。验证包括真实端口占用、网关/发布器一致性及配置保持。

## Planned（规划中）

新增相机或编解码器时，必须以兼容配置和生命周期的方式扩展。任何客户端均不得直接打开 ROS 图像 Topic。
