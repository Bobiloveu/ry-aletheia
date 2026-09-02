# aletheia_visualization

Aletheia HMI 的 Unity PoC 渲染数据传输插件。它将轻量 Unity 实例嵌入为 Flutter platform view，并向其转发地图、相机变换、位姿和点云缓冲区。

**边界：** 本包仅传输渲染数据。它绝不调用 ROS2、机器人 Backend、任务服务、任务恢复或视频；这些能力全部留在 Flutter App 中。

## 组成

| 部分 | 路径 | 职责 |
| --- | --- | --- |
| Dart API | `lib/` | `AletheiaVisualizationView`（platform view）+ `VisualizationController`（MethodChannel）+ `CloudBridge`（dart:ffi） |
| 原生桥接 | `../shared/aletheia_viz_bridge.{c,h}` | 一个 latest-wins 点云暂存缓冲和指标；每个平台只编译一次。iOS 中它位于 `aletheia_visualization.framework`，由 Swift、Dart FFI 与 Unity 共同解析。 |
| Android 胶水层 | `android/` | Kotlin 插件 + platform view；由 `aletheia.unityEnabled` 选择 `src/stub` 或 `src/unity` |
| iOS 胶水层 | `ios/` | Swift 插件 + platform view；Unity 路径由 `ALETHEIA_UNITY_ENABLED` 控制 |

## 点云路径（唯一关键规则）

`CloudFrameDecoder` (in the app) → packed `Float32List` →
`VisualizationController.pushCloud` → `CloudBridge.stage` (one bulk copy into a
reused native buffer, FFI) → `av_cloud_stage` → Unity `av_cloud_acquire` on its
render thread → `GraphicsBuffer` → GPU point shader.

不使用 JSON，不逐点调用 MethodChannel，不进行对象转换。采用 latest-wins：无论 Unity 是否消费，新帧都会覆盖上一帧。时效门限（cloud > 100 ms）保留在 Dart 遥测客户端。

XY 或 XYZ 的最大点数均为 **262,144**。Dart FFI 调用、C 桥接和 `PointCloudRenderer` 都强制此上限；float 数量不能被布局整除的畸形帧，或虽能放入原始 float 存储但超过 GPU 点分配的 XY 帧，均在 `GraphicsBuffer.SetData` 前拒绝。

## 使用 Unity 构建

参见 `../../../unity/README.md`。在 Unity 库导出并接入前，插件构建为 stub surface，App 使用自身 Flutter 渲染器。
