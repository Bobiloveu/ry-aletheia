# 低延迟视频兼容性与开销控制

## 目标与证据

用户报告两台车前后左右四路均无画面；其中一台从 i7-9700T 平台更换为 Xeon E5-2673 v4＋NVIDIA RTX A2000。当前实现固定 Intel VAAPI/iHD，尚未使用 NVIDIA NVENC。审查还复现格式拒帧、一路输入退出导致全停、运行时同标记不修复缺文件、浏览器假在线/悬挂请求/过时会话问题。

参考 `/home/bob/Desktop/shmsdk/0922/recv_img.cpp.pdf`（2026-09-22，实际为 SDK 手册）：GET_LAST、一次初始化、独立通道、JPEG 内容解码可沿用；示例的无条件 imdecode、失败 break 和固定 sleep 不能直接作为生产接收器。SDK 文档所称零拷贝不能替代实际公开 API 的复制语义；静态库审查显示 OpenMem 会经过 mempool once 启动逻辑，验证程序禁止调用真实 SDK/共享内存。

## 设计

1. 保留每路原生输入进程与 MediaMTX/WHEP 架构，Python 不传视频帧。DDS 与 ShmSDK 的源配置继续明确，不在后台猜测切换源。
2. 原生读取回调只覆盖最新槽，限帧后的 worker 才解码 JPEG/准备编码输入。紧凑 raw 帧直接使用原缓冲；带 padding 的合法帧通过显式 stride 传给 rawvideoparse。JPEG 用 libjpeg，避免引入 OpenCV 大运行时。支持 JPEG/JPG/MJPEG、rgb8/bgr8/rgb24/bgr24、mono8、RGBA/BGRA、明确字节序的 YUYV/UYVY；未知或不完整帧有界拒绝。用 JPEG 头验证实际尺寸，限制尺寸/字节数；原始帧严格校验尺寸、stride 与长度。
3. 编码目标仍由 resolution/fps/bitrate 配置决定。实际源尺寸改变时重建对应单路管线；同尺寸无需逐帧重建。固定输出帧率与 latest-wins 保留，输入分辨率适配经受控缩放。
4. `runtime.encoder` 增量支持 auto、vaapih264enc、nvh264enc；旧正常 Intel 设备优先继续 VAAPI，E5＋A2000 选择 NVENC。不以高占用软件编码作为自动回退。私有 runtime 增加锁定包已有 nvcodec 插件，NVIDIA 内核驱动/用户驱动仍由车端系统拥有。实际硬件编码预检仅在用户启用视频时执行一次，使用有界合成帧测试、超时和失败缓存，不读真实相机。
5. 修复单路异常的故障域：有界退避只重启该路，保持 MediaMTX 和其它流；网关自身退出才停止全局。runtime 摘要涵盖锁文件/包装器/插件内容，启动时校验必需文件；不覆盖 config/video.json。
6. 状态增量增加 runtime/encoder 诊断，原 stream status 枚举保留。Web 按实际首帧判定播放、对连接/首帧设置期限，正确清理过时 WHEP 响应与异步 Pixi 初始化；Mobile 原字段继续兼容并做定向消费验证。

## 性能要求与验证边界

- 不增加相机/图像 DDS 发布者，不修改驱动、mempool、ROS 图或导航；不积压历史帧，不引入 Python 帧复制/转码。
- 原正常 640×480/15 FPS 输入的吞吐、CPU 和内存用同条件基线对比；超帧率 JPEG 先丢弃旧帧再解码，验证解码次数与输出预算一致。
- raw 紧凑/stride 路径验证无多余全帧复制；只有 JPEG 解码或必须的缩放才分配对应输出。
- 原生格式/管线用无 ROS、无 SDK 的 C++ 单测验证；ROS target 进行实际编译。私有 runtime 做依赖闭合和插件验证。Web 用真实函数/私有模拟 WHEP 故障注入验证。
- 实车 GPU 利用率与端到端延迟必须以同帧率、同分辨率、同客户端实测，不把模拟 CPU benchmark 当成硬件验收。此阶段不重启现场服务或调用实际 SDK。

## 分工与边界

Backend/runtime 与打包、C++ 原生帧处理、Web 生命周期是独立实施单元。共享契约先更新，随后 TDD、独立审查和相关 Backend/Web 检查。保留现有全部工作区改动；不提交或发布构建产物。
