# aletheia_visualization

Renderer-transport plugin for the Aletheia HMI's Unity PoC. Embeds a
lightweight Unity instance as a Flutter platform view and forwards a map, a
camera transform, a pose and a point-cloud buffer to it.

**Boundary:** this package is a transport for rendering data only. It never
calls ROS2, the robot backend, task services, mission recovery or video. All
of that stays in the Flutter app.

## Shape

| Piece | Path | Role |
| --- | --- | --- |
| Dart API | `lib/` | `AletheiaVisualizationView` (platform view) + `VisualizationController` (MethodChannel) + `CloudBridge` (dart:ffi) |
| Native bridge | `../shared/aletheia_viz_bridge.{c,h}` | one latest-wins point-cloud staging buffer + metrics; compiled once per platform. On iOS it lives in `aletheia_visualization.framework`, which Swift, Dart FFI and Unity all resolve. |
| Android glue | `android/` | Kotlin plugin + platform view; `src/stub` vs `src/unity` selected by `aletheia.unityEnabled` |
| iOS glue | `ios/` | Swift plugin + platform view; Unity path behind `ALETHEIA_UNITY_ENABLED` |

## Cloud path (the one rule that matters)

`CloudFrameDecoder` (in the app) → packed `Float32List` →
`VisualizationController.pushCloud` → `CloudBridge.stage` (one bulk copy into a
reused native buffer, FFI) → `av_cloud_stage` → Unity `av_cloud_acquire` on its
render thread → `GraphicsBuffer` → GPU point shader.

No JSON. No per-point MethodChannel. No object conversion. Latest-wins: a new
frame overwrites the previous one whether or not Unity consumed it. Freshness
gates (cloud > 100 ms) stay in the Dart telemetry client.

The maximum is **262,144 points** for either XY or XYZ. This is enforced in
the Dart FFI call, the C bridge and `PointCloudRenderer`; a malformed frame
whose float count is not divisible by its layout, or an XY frame that only
fits the raw float storage but exceeds the GPU point allocation, is rejected
before `GraphicsBuffer.SetData`.

## Building with Unity

See `../../../unity/README.md`. Until the Unity library is exported and wired
in, the plugin builds with a stub surface and the app uses its own renderer.
