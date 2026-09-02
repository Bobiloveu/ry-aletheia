// CocoaPods only compiles sources beneath the plugin's iOS root. Keep this
// translation unit deliberately thin: the shared bridge remains the one
// implementation used by Android and iOS, while this file makes it part of
// the iOS plugin target. Flutter FFI and Unity resolve this one loaded
// framework image, so they share exactly one staging buffer.
#include "../../shared/aletheia_viz_bridge.c"

int32_t av_metrics_read_values(
    float *render_fps,
    float *frame_ms_p50,
    float *frame_ms_p95,
    int32_t *last_point_count,
    int64_t *cloud_seq) {
  av_metrics metrics;
  int32_t result = av_metrics_read(&metrics);
  if (result != 0) return result;
  if (render_fps != NULL) *render_fps = metrics.render_fps;
  if (frame_ms_p50 != NULL) *frame_ms_p50 = metrics.frame_ms_p50;
  if (frame_ms_p95 != NULL) *frame_ms_p95 = metrics.frame_ms_p95;
  if (last_point_count != NULL) *last_point_count = metrics.last_point_count;
  if (cloud_seq != NULL) *cloud_seq = metrics.cloud_seq;
  return 0;
}

int32_t av_renderer_is_ready_value(void) {
  return av_renderer_is_ready();
}
