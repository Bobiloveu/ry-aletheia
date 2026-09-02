# 视频

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/video.py`、`web_console.py`、`frontend/src/liveObservation.js` 和 `mobile/lib/features/live_observation/`
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

`GET /api/video/status` 返回已配置的视频流和运行时健康状态。`POST /api/video/control` 是客户端控制全局或单路启用状态的唯一入口。客户端必须使用返回的已配置流名称，不能自行拼接相机端点。

实际视频像素通过媒体网关到浏览器或 Mobile 的只接收 WHEP/WebRTC 会话传输。Python 只管理配置、进程生命周期和健康状态，不转发视频帧。离开视频工作区、切换流、App 进入后台或销毁视图时，必须释放对应会话、PeerConnection、媒体流和 renderer。

## Planned（规划中）

新增相机或编解码器时，必须以兼容配置和生命周期的方式扩展。任何客户端均不得直接打开 ROS 图像 Topic。
