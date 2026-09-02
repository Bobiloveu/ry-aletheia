/*
 * aletheia_viz_bridge — the single high-throughput seam between the Flutter
 * data layer and the embedded Unity renderer.
 *
 * Design rules (do not weaken):
 *   - Point-cloud data crosses here as a packed float buffer only. No JSON, no
 *     per-point marshalling, no object graphs. Camera intent uses the same
 *     latest-wins rule, but is only eight scalar values.
 *   - Exactly one pending frame is retained (latest-wins). A new stage() call
 *     overwrites whatever the renderer has not consumed yet.
 *   - Zero allocation on the hot path. The staging buffers are sized once for
 *     the maximum supported point count and reused.
 *   - This file is compiled once, into the Flutter plugin's native artefact.
 *     Unity resolves the same symbols at runtime (same process under Unity as
 *     a Library): DllImport("aletheia_viz_bridge") on Android and the loaded
 *     `aletheia_visualization.framework` image on iOS.
 */
#ifndef ALETHEIA_VIZ_BRIDGE_H
#define ALETHEIA_VIZ_BRIDGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#define AV_EXPORT __declspec(dllexport)
#else
#define AV_EXPORT __attribute__((visibility("default")))
#endif

/* Hard ceiling. 2D = 2 floats/point, 3D = 3 floats/point. Sized for the 200k
 * stress target with headroom. */
#define AV_MAX_POINTS 262144
#define AV_MAX_FLOATS (AV_MAX_POINTS * 3)

/* Point layout of a staged frame. */
typedef enum {
  AV_CLOUD_XY = 2,  /* packed float32 x,y      (current 2D telemetry) */
  AV_CLOUD_XYZ = 3, /* packed float32 x,y,z    (3D LiDAR, M3+)        */
} av_cloud_layout;

/*
 * Called from the Flutter isolate (via dart:ffi) whenever a new decoded cloud
 * frame is accepted by the Dart client. `xy` points into the Dart
 * Float32List; `float_count` is its length (points = float_count / layout).
 * Returns the sequence number assigned to the staged frame, or -1 if the
 * frame was rejected (too large / null).
 *
 * Thread-safe against av_cloud_acquire().
 */
AV_EXPORT int64_t av_cloud_stage(const float *xy, int32_t float_count,
                                 int32_t layout);

/*
 * Called from the Unity render loop once per frame. If a frame has been staged
 * since the last acquire, copies it into `out` (capacity `out_capacity`
 * floats), sets *out_float_count and *out_layout, and returns the sequence
 * number. Returns 0 when there is nothing new. Returns -1 on buffer overflow.
 *
 * Unity must treat the copied data as latest-wins: never accumulate history.
 */
AV_EXPORT int64_t av_cloud_acquire(float *out, int32_t out_capacity,
                                   int32_t *out_float_count, int32_t *out_layout);

/* Age, in milliseconds, of the most recently staged frame (monotonic clock at
 * stage time vs now). Lets Unity drop a frame the same way the Dart client
 * would (cloud > 100 ms). */
AV_EXPORT int64_t av_cloud_age_ms(void);

/* --- lightweight render metrics, Unity -> Flutter (polled) --- */
typedef struct {
  float render_fps;
  float frame_ms_p50;
  float frame_ms_p95;
  int32_t last_point_count;
  int64_t cloud_seq;
} av_metrics;

/* Unity writes this ~1x/second. */
AV_EXPORT void av_metrics_report(const av_metrics *m);
/* Flutter reads it on a timer. Returns 0 on success. */
AV_EXPORT int32_t av_metrics_read(av_metrics *out);

/* Unity calls this from VizBridge.Start once the scene object that receives
 * Flutter messages exists. The host must not send map data before this point:
 * UnitySendMessage intentionally drops messages for objects that have not
 * been instantiated yet. */
AV_EXPORT void av_renderer_set_ready(int32_t ready);
AV_EXPORT int32_t av_renderer_is_ready(void);

/* --- camera intent, Flutter -> Unity render loop ----------------------- */
/*
 * The Flutter map gesture surface stages the newest camera state directly in
 * this process-local buffer. Unity consumes it in LateUpdate. Keeping this
 * off MethodChannel/UnitySendMessage is essential on 120 Hz touch hardware:
 * camera updates must never queue behind large map or UIKit work.
 */
typedef struct {
  float scale;
  float ox;
  float oy;
  float yaw;
  float pitch;
  float distance;
  float tx;
  float ty;
  /* Flutter PlatformView ID that owns this intent. Unity discards camera
   * writes from a departing fullscreen/card surface after a host swap. */
  int64_t owner;
  /* Complete Flutter logical viewport. Unity must not derive this projection
   * from a transient embedded SurfaceView buffer during a route transition. */
  float viewport_width;
  float viewport_height;
  float pixels_per_metre;
  float center_x;
  float center_y;
  int64_t viewport_revision;
} av_camera;

/* Copies one complete camera intent into the latest-wins slot. Returns a
 * positive sequence number, or -1 for invalid/non-finite values. */
AV_EXPORT int64_t av_camera_stage(const av_camera *camera);

/* Copies an unseen camera intent into `out`. Returns its sequence number,
 * 0 when unchanged, or -1 for a null output pointer. */
AV_EXPORT int64_t av_camera_acquire(av_camera *out);

/* Reset all state. Called on engine unload so a re-created Unity instance
 * never sees a stale frame. */
AV_EXPORT void av_bridge_reset(void);

#ifdef __cplusplus
}
#endif

#endif /* ALETHEIA_VIZ_BRIDGE_H */
