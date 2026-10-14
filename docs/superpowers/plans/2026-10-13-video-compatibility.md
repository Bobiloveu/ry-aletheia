# 视频兼容性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 提高 DDS/ShmSDK 图像输入与 Intel/NVIDIA 编码兼容性，修复无画面恢复，并验证原有低延迟与占用预算。

**Architecture:** 保留 native → private GStreamer → MediaMTX → WHEP；输入统一最新槽/限帧解码，按已验证硬件选择编码器，逐路恢复，客户端验证首帧。

**Tech Stack:** C++17/libjpeg、Python、锁定 GStreamer 1.20/NVENC/VAAPI、WebRTC/PixiJS。

**Spec:** `docs/superpowers/specs/2026-10-13-video-compatibility-design.md`。

## Global Constraints

- 不调用实际 SDK/共享内存，不启动、重启现场视频、ROS、Supervisor 或相机；不改导航安全边界。
- 既有字段/枚举保持兼容；源配置明确；不自动切换 ROS/ShmSDK。
- Python 不承载帧；latest-wins、有界缓存、原输出预算保持。
- 不默认软件编码，不自动安装系统/显卡驱动；现有 Intel 可用路径优先。

### Task 1: Native 输入/管线

Files: `live_preprocessor/src/video_ingest.cpp`、新增纯 C++ frame/pipeline helper 与测试、CMake target。

- [x] 为 JPEG 内容/别名、raw stride、颜色/尺寸、坏帧、有界缓存/限帧、NVENC/VAAPI argv 编写失败回归。
- [x] 实现共用格式处理、最新槽后解码、目标尺寸适配和正确 stride。
- [x] 运行纯 C++ 测试与 ROS target 构建；记录可复现开销 benchmark。

### Task 2: Backend 编码能力与逐路恢复

Files: `autodrive_console/video.py`、编码选择 helper、`build_video_runtime.sh`、配置模板、相关测试。

- [x] 测试 Intel 保留、A2000/NVENC 分支、无硬件清晰错误、旧配置兼容、单路恢复与其它路不重启。
- [x] 补齐私有 nvcodec 与所需 ELF 依赖、runtime 内容指纹及必需文件验证。
- [x] 模拟探测/故障验证不读相机、不逐次启动探测，保留旧视频字段。

### Task 3: 客户端实际播放与恢复

Files: `frontend/src/liveObservation.js`、可测 WHEP helper、Web 回归测试；Mobile 消费契约定向核对。

- [x] 将审查的五个 VM 缺陷改为预期正确行为的失败测试。
- [x] 修复 WHEP/首帧期限、播放失败恢复、过时会话清理、异步渲染销毁。
- [x] 状态显示区分输入、编码和客户端故障，不再把所有等待称为 ROS 图像。

### Task 4: 集成验收

- [x] 独立审查与性能比较，修复发现的问题。
- [x] Backend 全量 1430 项、Web 729 项、最新视频专项 56 项、C++ 编译/单测、私有 runtime 与 Backend/Web doctor 已通过。
- [x] 记录实际验证范围及尚需现场同条件验证的 GPU/端到端指标，不以模拟结果替代实车结论。
