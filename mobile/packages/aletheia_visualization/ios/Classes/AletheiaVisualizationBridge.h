#ifndef ALETHEIA_VISUALIZATION_BRIDGE_H
#define ALETHEIA_VISUALIZATION_BRIDGE_H

// A narrow Swift-facing adapter for the shared renderer bridge. The complete
// C transport contract stays in ../../shared; this header deliberately only
// exposes scalar metrics so CocoaPods' generated module never depends on a
// header outside the plugin's iOS source root.
#include <stdint.h>

int32_t av_metrics_read_values(
    float *render_fps,
    float *frame_ms_p50,
    float *frame_ms_p95,
    int32_t *last_point_count,
    int64_t *cloud_seq);

int32_t av_renderer_is_ready_value(void);

// Unity-as-a-Library creates its own UIWindow during bootstrap.  Flutter owns
// the visible application window, so the Unity Metal display must be rebound
// to the Flutter platform-view container after that bootstrap completes.
// Pointers are UIKit object pointers and are intentionally opaque here to
// keep this bridge usable from Swift without importing Unity private headers.
void av_unity_rebind_surface(void *unity_controller,
                             void *unity_view,
                             void *host_window);

#endif /* ALETHEIA_VISUALIZATION_BRIDGE_H */
