# 视频兼容性审查与改进记录（2026-10-13）

范围：Aletheia 的 DDS `sensor_msgs/Image` / ShmSDK `Cam*` 输入、原生 H.264 编码、私有 MediaMTX 与浏览器播放。现场反馈为四路前后左右均无画面；新车主机为 E5-2673 v4，用户补充 GPU 核心为 GA107、此前称 A2000。老车的现场 `nvidia-smi` 已确认是 i7-9700T＋NVIDIA P106-100，驱动 535.288.01（界面显示 CUDA 12.2 支持）。当前没有两起现场的完整运行日志，以下区分已复现的兼容性缺口与尚未确认的现场原因。

当前状态：源码改进与本地回归已完成；实车 GPU 与端到端性能仍待验收。没有启动现场视频、加载真实 SDK、打开共享内存或操作相机/ROS/Supervisor。

## 示例带来的启发

输入文件 `/home/bob/Desktop/shmsdk/0922/recv_img.cpp.pdf` 实际是 2026-09-22 的十页中间件手册；第九页包含接收图像示例。它使用 `GET_LAST` 并把数据交给 JPEG 解码器，说明读取最新帧、依据真实图像内容确认压缩格式比死守某一 metadata 值更稳妥。

示例不能直接作为生产实现：固定 sleep 会限制消费频率；逐帧显示和无条件解码会增加开销；`hId > 0` 与手册的失败值 `-1` 定义不一致；示例发送端 raw BGR 与接收端无条件 JPEG 解码也不一致。手册本身提醒示例可能不是最新版本。改进保留最新帧原则，使用轻量 libjpeg 和显式 raw 格式/stride 校验，不引入 OpenCV。

## 已确认的问题

| 层次 | 原行为与复现 | 影响 |
| --- | --- | --- |
| 硬件编码 | 原生管线写死 `vaapih264enc`；配置也只允许该编码器；私有运行时未暴露 nvcodec 插件 | 原 Intel 主机可用不代表 E5＋A2000 可用，四路共用的编码前提可能同时失败 |
| 图像格式 | 原 SHM 处理只接受指定尺寸的 JPEG/JPG/RGB8/BGR8，要求 raw 完全无填充 | 有效的 rgb24、MJPEG、YUYV、行填充或尺寸变化被拒绝；DDS 也有严格布局限制 |
| 行布局 | 用合成 RGB 帧实际运行 `rawvideoparse`：854×480 的紧密行长为 2562，默认按 2564 解释 | 两帧输入 2,459,520 字节只产生 1,230,720 字节输出，必须明确 plane stride |
| 解码预算 | 原 SHM 收到 JPEG 即完整解码，随后 worker 才限帧 | 来源高于输出帧率时，丢弃帧也消耗 JPEG 解码 CPU |
| 故障隔离 | 纯 mock 复现任一路 ingest 退出导致 runner 结束、所有 ingest 与 MediaMTX 被停掉 | 一路检测/分割失败可能使四路物理相机一起消失 |
| 升级与配置 | 版本 marker 相同会跳过损坏文件修复；marker 未覆盖 runtime 内容；显式默认 ROS input 不会迁移 SHM | 同 SDK 版本、不同升级历史仍可能走不同链路 |
| Web | 对实际源码的五个独立复现：WHEP 无截止期限、连接成功但无首帧不重试、play 失败不释放、过时响应覆盖新会话、Pixi 异步初始化后销毁泄漏 | 网络/API 正常并不能保证浏览器已有可显示画面 |

Intel 官方规格列出 [i7-9700T 的 UHD 630 与 Quick Sync](https://www.intel.com/content/www/us/en/products/sku/191048/intel-core-i79700t-processor-12m-cache-up-to-4-30-ghz/specifications.html)；Intel 说明 [Xeon E5 不支持 Quick Sync](https://www.intel.com/content/www/us/en/support/articles/000034104/processors/intel-xeon-processors.html)。[NVIDIA 编码支持矩阵](https://developer.nvidia.com/video-encode-decode-support-matrix) 列出 RTX A2000 的 H.264 NVENC 支持。因此“以前视频没用 NVIDIA GPU”不能排除旧主机实际用了 Intel 编码。用户后来提供的老车型号 P106-100 与 GTX 1060 不能混同；[NVIDIA 官方答复](https://forums.developer.nvidia.com/t/nvenc-and-gp106-100/67850) 明确其不含 NVENC。最终策略保留旧车 Intel 编码、新车实际预检通过后使用 NVENC，不强制所有 NVIDIA 卡走同一编码器。

行布局依据另见 [GStreamer rawvideoparse 文档](https://gstreamer.freedesktop.org/documentation/rawparse/rawvideoparse.html)。网络还需分别确认 WHEP HTTP 信令与 WebRTC 媒体链路；[MediaMTX 文档](https://mediamtx.org/docs/features/webrtc-specific-features) 说明两者端口与连通性不同。未取得现场证据前，不能把某一个兼容缺口直接认定为两起反馈的唯一原因。

## SDK 的真实边界

静态核对已安装的 2.8 与 2.8.4：相机公共结构的大小/偏移兼容，适配器所用函数符号存在；纯头文件 ABI 检查得到 Header=48、CamImage=128、getParm=24。适配器通过动态装载调用 SDK，不静态链接 SDK 实现。

两个版本的公共 `OpenMem` 都会调用内部 `start_mempool`，fork/exec `/usr/local/lib/mempool once`。因此旧文档“只读打开、不会启动 mempool”不能作为 SDK 保证。工具不会主动配置、停止或重启机器人 mempool，也不会为了绕开这个问题调用 SDK 私有 ABI；完全没有自动初始化副作用的打开方式需要供应方提供公开接口。本次检查没有加载或执行真实 SDK。

`GetCamImage` 会复制到调用者 vector，并以调用线程的消费上下文读取最新帧；不是借用随时被覆盖的共享指针。不要把手册的“零拷贝”宣传直接当成端到端事实。默认 Cam 池容量约 1 MiB，raw 720p 三通道超过该容量；扩大上游池的所有权仍属于机器人系统，本工具不能自动修改。

SDK 自身 OpenMem 失败时内部重试可阻塞约十秒，外层二秒重试间隔不代表完整调用只等二秒。SDK 时间戳语义也不能直接假定为 Unix wall clock；本工具不会未经校验就拿它判断画面新鲜度。

静态分析对象的 libfastshm SHA-256：

- 2.8：`9affe77ef563c13a12eb018c440c1d9484d5fcac3c17931bff36bd448be541b3`
- 2.8.4：`7dfccd6b7a5fbd500a18fd998890ae2ec2fc417ad748ba43b60e6dbf4ab73bc9`

## 实施与验证原则

设计见 [兼容性设计](../superpowers/specs/2026-10-13-video-compatibility-design.md)，实施检查项见 [实施计划](../superpowers/plans/2026-10-13-video-compatibility.md)，接口影响见 [视频契约](../../shared/contracts/video.md)。

保留原生进程、最新槽、既有输出 fps/resolution/bitrate；Python 不传视频像素。输入按实际内容与布局校验，昂贵解码在输出预算内执行。编码器优先保留原 Intel VAAPI，增加 NVIDIA NVENC，不自动降为高 CPU 软件编码。失败按单路退避恢复；浏览器以真实首帧判定播放。

本地合成输入能验证格式、生命周期与处理工作量，但不能替代 E5＋A2000 和原 Intel 车型的四路并发实测。要承诺“占用不变或更低”，仍需同相机输入、同输出预算、同网络条件，对照记录 CPU、RSS、GPU 编码负载、实际 FPS、首帧时间和端到端延迟。没有这些数据时不承诺实车百分比提升。

## 已落实的改进

- DDS 与 SHM 共用最新槽、限帧后准备、raw 原缓冲/stride 直传与 JPEG 大缓冲复用。来源尺寸/布局变化时仅重建该路管线，配置输出预算保持。
- Intel VAAPI 与 NVIDIA NVENC 使用真实编码预检，每候选最多四秒；关闭时可取消，不每次读取状态都探测。默认先保留可用 Intel；没有硬件时明确报错，不自动上高 CPU 软件编码。
- NVENC 参数核对锁定 1.20.3 源码，使用无 B 帧、低延迟、CBR/GOP 和 constrained-baseline。VAAPI 将实际选择的 DRM 节点传给编码进程。
- 私有 runtime 的 57 个 DEB 逐个锁定 SHA-256，并递归静态验证 ELF 依赖闭合；NVIDIA 驱动仍由车端提供。内容指纹、必需文件、哈希与执行位用于刷新/修复；私有 scanner 同时固定版本化与非版本化环境变量。
- 一路 ingest 退出只退避恢复该路，最多五次，保留其余流与 MediaMTX；停用使用受控进程组及有界回收。预检可取消，native 绑定父进程生命周期。
- Web 以解码帧确认播放，增加建连/响应体、首帧与停帧恢复；清理过时会话、play 失败、异步渲染销毁和旧画面。关闭 Pixi 重复帧更新，不增加高频 stats 轮询。
- 交叉审查还修复了 raw 首像素恰好为 `FF D8 FF` 被误认为 JPEG、配置/native FPS 范围不一致、预检停用遗留、私有 scanner 被外部环境覆盖及执行权限丢失无法修复的问题。

## 本地验证结果

| 检查 | 结果与范围 |
| --- | --- |
| 视频 Python 专项 | 56 passed，包含真实锁定依赖解包/静态 ELF 校验；GPU/进程故障测试使用模拟边界 |
| Web 必需检查 | `scripts/test-web.sh`：729 passed、parity 与生产构建通过 |
| 纯 C++ | CTest 2/2；ASan＋UBSan 2/2；包含格式、JPEG 边界、最新槽、管道期限和合成进程回收 |
| ROS 编译 | 通过现有 ROS 环境编译真实 `aletheia_video_ingest` target，未启动节点 |
| 实际 CPU GStreamer | 九种 raw 格式/stride 两帧完整通过，854 宽及填充行均正确；不加载 GPU 插件 |
| Chromium | 真实视频元素＋Pixi 显示合成 640×480 帧；单路停帧重连时另一 peer 保留，错误后清空旧画面；WHEP/Peer 为模拟 |
| 真实隔离传输链路 | 合成源→CPU x264 constrained-baseline→RTSP→锁定 MediaMTX 1.19.2→实际 WHEP/WebRTC→Chromium H.264 解码→Pixi，通过；两张卡片读取同一源，均为 640×480 / 15 FPS / 515 个解码帧。不是两路相机或 NVENC 硬件测试；自建会话与进程均已回收 |
| 离线检查 | `pixi run test-offline`：109 passed |
| 环境 | Backend/Web doctor 通过 |
| Mobile | 原解析只读取既有字段，增量诊断为可选；定向静态核对，无 Mobile 源码变更。此环境无 Flutter 工具链，未运行 Flutter 测试 |
| Backend 全量 | `scripts/test-backend.sh`：1430 passed（17 分 19 秒）；后续审查新增边界另以最新 56 项视频专项复核通过 |

可复查入口：`tests/test_video_manager.py`、`tests/test_video_runtime.py`、`tests/test_video_runtime_packaging.py`、`frontend/test/live-observation-video.test.mjs`、`live_preprocessor/test/`。纯 native 检查可用 `-DALETHEIA_NATIVE_TESTS_ONLY=ON` 构建，不需要 ROS/SDK。测试记录暂存在 `/tmp/ry-video-audit/`；浏览器故障恢复记录位于 `/tmp/aletheia-video-browser-recovery.json`；真实隔离 WHEP 记录、截图及日志位于 `/tmp/aletheia-e2e/`。

### CPU 准备阶段对比

同机、640×480 合成帧，旧处理函数与新 helper 使用相同 libjpeg、编译优化。每场景三轮，表中取中位数。没有真实 SDK、GPU、网络或摄像头。

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| raw 准备耗时 | 43.24 μs/帧 | 0.0555 μs/帧 |
| raw 额外完整帧分配 | 921600 bytes/帧 | 0 |
| JPEG 准备耗时 | 479.3 μs/帧 | 400.1 μs/帧 |
| 模拟十秒、30→15 FPS 的解码次数 | 300 | 150 |
| 上述 JPEG 解码 CPU 时间 | 145.3 ms | 58.5 ms |

JPEG RGB 大缓冲复用；libjpeg 安全状态仍有约 1224 bytes/帧的小分配，未包含 libjpeg 自身内部 malloc。上表只描述 CPU 准备阶段，不能解读为整个视频链路 CPU 降低同样百分比。原 SDK 到 vector 的复制仍存在，不宣称端到端零拷贝。

### 另一路径的隔离试验

按用户追加要求，尝试 `压缩 JPEG → jpegparse → jpegdec → NV12`，与 `C++ libjpeg → RGB 管道 → NV12` 比较。同一合成 640×480、质量 85 的 JPEG，单帧 202321 bytes，每轮 300 帧、四轮，CPU GStreamer 1.20.1，仅暴露六个 CPU 插件；下游为 fakesink，未使用 GPU/媒体网关。以下为四轮中位数：

| 指标 | C++ 解码＋RGB 管道 | 压缩 JPEG 管道 |
| --- | ---: | ---: |
| 两进程合计 CPU 时间 | 1.405 s | 0.975 s |
| 管道数据量 | 276480000 bytes | 60696300 bytes |
| 总处理时间 | 0.903 s | 0.970 s |
| 生产进程峰值 RSS | 5760 KiB | 4928 KiB |
| GStreamer 峰值 RSS | 17632 KiB | 16410 KiB |

压缩路径 CPU 约减少 31%、管道数据减少约 78%，但该吞吐试验总时间略增约 7%。两进程 RSS 峰值分别记录，不能相加视为同一时刻的总峰值。此结果没有真实硬件编码、帧率限制或端到端延迟，也未覆盖现场坏 JPEG、格式切换与断流恢复。因此作为候选保留，**没有直接替换生产路径**。试验源码/数据位于 `/tmp/ry-video-audit/jpeg-pipe-*`，未打包到运行程序。

## 实车验收范围

源码检查不能替代两类车现场验收。分别在 i7-9700T＋P106-100 与 E5-2673 v4＋GA107 上，按原配置一次开一路、再开四路，并记录实际所选编码器、FPS、CPU、RSS、Intel/NVIDIA 编码负载、首帧时间、端到端延迟和关闭后资源回收。相机输入与输出 resolution/fps/bitrate 必须保持一致才能比较。额外核对两路检测/分割故障时四路物理流继续播放，以及视频关闭期间不做探测。

截至 2026-10-13 审查时，未发布新 ZIP/DEB、未更新或重启实车程序；没有把本地模拟结果标为量产硬件已验收。

## 2026-10-14 新主板实车链路排查

本节追加现场证据，不将上述历史的本地验证数字视为本次结果。车辆使用 E5-2673 v4、RTX A2000 Laptop GPU、
580.178.04 驱动、工具 2.8.10；四路 ShmSDK 输入为 RGB，检测与分割 ROS 输入为 BGR，均为
640×480。车端时钟不正确，排查采用单调时间、计数器差值与文件偏移，不依据其日志日期判断先后。

### 首帧时间戳与 NVENC

`/rfdetr_detect` 与 `/segmentation/overlay` 均实际收到有效图像。故障时原生输入仍持续读入，
MediaMTX 显示 ready，RTCP 仍有计数，RTP/媒体字节却停在首帧。只检查 ready 无法证明画面正常。
独立 RGB/BGR NVENC 文件输出成功，不能把此故障归为显卡不支持编码或只支持三路。

只对临时诊断进程采集的 GDB 栈显示 RTP 发布线程停在时钟等待，目标时间比正常时钟约远
1000 小时。GStreamer 1.20.3 的 `gstnvbaseenc.c` 在 start 时设置 1000 小时的 min-PTS。
后续逐帧日志进一步确定：首个编码输入 PTS 为 NONE，先发出了 start=0 的 segment；第二帧
才具有有效 PTS 并建立 min-PTS 偏移，已发出的 segment 未同步变化。正式定位/导航节点未调试或重启。

曾验证移除 `fdsrc do-timestamp=true` 可以出流，但短暂停流后的浏览器抖动缓冲增至约一秒，
因此撤销该候选，保留真实采集时间戳。修复在 rawvideoparse 后、原有单帧队列前增加两个
独立 identity：先 `sync=true` 等待 PLAYING，再 `drop-buffer-flags=discont` 丢弃启动首个完整帧；
均关闭 handoff 信号，不新增历史队列、不改变硬件编码、分辨率、帧率和码率预算。VAAPI 参数不变。

检测与分割双路测试中，仅暂停本次诊断接收进程四秒，未暂停原始 ROS 发布节点；恢复后继续
解码，三个后续五秒窗口的平均抖动缓冲等待约 3～14 毫秒。这是浏览器 jitter buffer 指标，
不是端到端延迟或 CPU 性能提升承诺。网络采样出现少量丢包，不能写为全程零丢包。

两轮六路同时启动的首个编码输入 PTS 均有效，约 0.0003～0.34 秒，后续单调，没有 NONE 或
uptime 级首帧。一次后续试验出现检测/分割一个五秒窗口无媒体增长，当时未同步采集源端计数，
不能确定该窗口是否为源端停顿；不据此宣称全部断流场景已消除。补充的一轮六路测试同步记录
原生写入与 MediaMTX 媒体计数，连续 90 秒、每五秒检查均有增长。六路实际 WHEP 解码均为
640×480；其中十五秒浏览器采样如下：

| 通道 | 实际解码 FPS | 平均抖动缓冲等待 |
| --- | ---: | ---: |
| 前相机 | 14.97 | 14.03 ms |
| 后相机 | 14.97 | 6.10 ms |
| 左相机 | 14.97 | 11.42 ms |
| 右相机 | 14.97 | 6.74 ms |
| 目标检测 | 7.42 | 5.46 ms |
| 可通行区域分割 | 9.98 | 9.07 ms |

该十五秒窗口六路 packetsLost 均为零，不扩展为整个排查期间零丢包。检测送入编码管道的计数约
35～39 帧/五秒，低于配置的十帧上限；它不是源 Topic 的完整发布计数，不能把配置 FPS 或
编码输入 FPS 当作源端实际发布 FPS。
测试只使用工具自有的临时输入/编码/网关进程，退出后经标准 API 恢复原视频配置，JSON 比较一致；
未保留临时原生运行库，也未修改原始图像生产端。

### 网关争抢与日志体积

六路全部关闭时，工具正常回收私有网关，随后系统 `mediamtx.service`（`Restart=always`，
使用 `/etc/mediamtx.yml`）抢占了 8554。该配置只开启 RTSP，关闭 API 与 WebRTC，工具再启动时
出现 bind address already in use。经用户单独确认后，临时停止该系统服务以恢复工具网关；
未禁用其开机启动，未改系统配置。随后实车重启再次复现同一冲突（查询时 uptime 约 197 秒），
再次按已有授权临时停止系统网关、恢复工具网关；此时状态接口已清除启动失败。

源码现已增加私有 RTSP 端口兜底：硬件预检后、本次私有网关启动前，使用 loopback bind 检查
配置端口；被占用时依次尝试 18554～18557，最后尝试系统分配端口，排除 API、WHEP 与 RTC
所用端口。仅 EADDRINUSE 进入下一候选；权限等其他错误立即失败。选择结果只保存在运行器中，
网关配置与所有发布器使用同一端口，单路恢复时重新读取用户配置也不会覆盖本次选择；用户配置
不回写，系统服务与对外 WHEP/API 地址不改变。

此检查不能原子保留端口：如果 bind 检查释放后端口又被其他进程抢占，仍通过既有的有界启动
失败路径报错，不能宣称消除所有并发争抢。实车保持现有 8554 网关运行，同时用源码中的选择器
及配置生成器启动隔离网关，实际选到 18554；NVENC 合成输入持续发布，浏览器实际解码 439 帧
640×480 图像。该隔离试验另外使用 API 18997、WHEP 18889、RTC 18189 避免干扰在用网关，
不是改写正式配置；诊断网关、编码器和浏览器连接均已清理。

`video-runtime.log` 约 1,637,251,282 bytes（1561 MiB）。九处有界抽样显示历史内容大量重复
`no element "vaapih264enc"` 与 Broken pipe 重试；当前 NVENC 排查期间没有同量级增长。
视频原始输出采用追加文件，尚无轮转；这是历史错误刷屏与无文件上限共同导致的积累。
本次未删除、截断该日志，亦未把时间戳修复误报为日志轮转已经完成。

本次检查：端口兜底增加前的完整 Backend 快照 1550 passed；最终源码经 Backend 脚本筛选
`video or tool_logging_http` 共 81 passed（包括新增五项端口测试）。离线 109 passed，发布构建中的
Web 763 passed、parity/生产构建通过，原生 CTest 2/2、ROS 原生节点编译通过，Backend doctor 通过。
全量复跑还暴露了既有 HTTP 审计测试在响应接收后立即读取日志的竞态；测试现按 request ID
有界等待审计记录，仍验证等级、关联与敏感信息过滤，未修改生产日志业务；该文件 11 passed。
排查阶段未自行打包或替换车端二进制；实车隔离验证不等同于原安装版本已获得修复。
恢复原安装版本后，四路物理相机重新确认持续出流，检测/分割媒体计数仍停滞；它们需要包含
本次修复的新构建才能获得永久修复。当前系统 MediaMTX 临时停止、开机自启仍启用；没有诊断
子进程遗留，测试浏览器接收会话已关闭。

### 用户授权后的 2.9.1 升级 ZIP

用户明确批准生成 ShmSDK 升级 ZIP 并自行部署后，执行 `./make_upgrade.sh 2.9.1 --shm`，
交付 `releases/2.9.1-shm/ry-aletheia_2.9.1_shm.zip`（88,686,994 bytes）。未生成 DEB，未安装到小车。
ZIP 仅含 manifest.json 与 ry-aletheia，Ed25519 签名、二进制 SHA-256/MD5/尺寸、ZIP CRC 与
SHA256SUMS 均已核验。包内四路默认输入确认为 CamFront/CamBack/CamLeft/CamRight 的 ShmSDK
通道，编码器默认 auto；嵌入的原生视频 ELF 与本次编译并通过 CTest 的目标一致，嵌入 Python
端口选择器字节码与最终源码一致。

ZIP SHA-256：`bcac95e6a7112767aee2f55dbd8fc89741aa76a23f4ceec0401f944bee9ea789`。
该版本修复视频启动时间轴与私有 RTSP 端口冲突兜底；未增加原始视频日志轮转，也未清理现有大日志。
