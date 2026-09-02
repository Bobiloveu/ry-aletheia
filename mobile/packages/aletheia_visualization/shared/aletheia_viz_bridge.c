/* See aletheia_viz_bridge.h for the contract. */
#include "aletheia_viz_bridge.h"

#include <math.h>
#include <string.h>
#include <time.h>

#if defined(__APPLE__)
#include <os/lock.h>
static os_unfair_lock g_lock = OS_UNFAIR_LOCK_INIT;
#define AV_LOCK() os_unfair_lock_lock(&g_lock)
#define AV_UNLOCK() os_unfair_lock_unlock(&g_lock)
#else
#include <pthread.h>
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
#define AV_LOCK() pthread_mutex_lock(&g_lock)
#define AV_UNLOCK() pthread_mutex_unlock(&g_lock)
#endif

/* Double buffer: producer writes g_back, av_cloud_acquire copies from it. A
 * single pending frame — latest-wins — so g_back is simply overwritten. */
static float g_back[AV_MAX_FLOATS];
static int32_t g_back_count = 0;
static int32_t g_back_layout = AV_CLOUD_XY;
static int64_t g_seq = 0;        /* last staged sequence            */
static int64_t g_consumed = 0;   /* last acquired sequence          */
static int64_t g_staged_at_ms = 0;

static av_metrics g_metrics;
static int32_t g_renderer_ready = 0;
static av_camera g_camera;
static int64_t g_camera_seq = 0;
static int64_t g_camera_consumed = 0;

static int64_t now_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int64_t av_cloud_stage(const float *xy, int32_t float_count, int32_t layout) {
  if (xy == NULL || float_count <= 0 || float_count > AV_MAX_FLOATS) {
    return -1;
  }
  if (layout != AV_CLOUD_XY && layout != AV_CLOUD_XYZ) {
    return -1;
  }
  /* Keep the native and Unity buffers at the same point-count ceiling. A
   * float-only bound allows 393,216 XY points into a 262,144-point GPU
   * buffer, which turns one malformed/oversized live frame into a render
   * thread failure. Reject partial points and over-capacity frames here. */
  if (float_count % layout != 0 || float_count / layout > AV_MAX_POINTS) {
    return -1;
  }
  AV_LOCK();
  memcpy(g_back, xy, (size_t)float_count * sizeof(float));
  g_back_count = float_count;
  g_back_layout = layout;
  g_staged_at_ms = now_ms();
  int64_t seq = ++g_seq;
  AV_UNLOCK();
  return seq;
}

int64_t av_cloud_acquire(float *out, int32_t out_capacity,
                         int32_t *out_float_count, int32_t *out_layout) {
  AV_LOCK();
  if (g_seq == g_consumed) {
    AV_UNLOCK();
    return 0; /* nothing new */
  }
  if (g_back_count > out_capacity) {
    AV_UNLOCK();
    return -1;
  }
  memcpy(out, g_back, (size_t)g_back_count * sizeof(float));
  if (out_float_count) *out_float_count = g_back_count;
  if (out_layout) *out_layout = g_back_layout;
  g_consumed = g_seq;
  int64_t seq = g_consumed;
  AV_UNLOCK();
  return seq;
}

int64_t av_cloud_age_ms(void) {
  AV_LOCK();
  int64_t staged = g_staged_at_ms;
  AV_UNLOCK();
  if (staged == 0) return -1;
  return now_ms() - staged;
}

void av_metrics_report(const av_metrics *m) {
  if (m == NULL) return;
  AV_LOCK();
  g_metrics = *m;
  AV_UNLOCK();
}

int32_t av_metrics_read(av_metrics *out) {
  if (out == NULL) return -1;
  AV_LOCK();
  *out = g_metrics;
  AV_UNLOCK();
  return 0;
}

void av_renderer_set_ready(int32_t ready) {
  AV_LOCK();
  g_renderer_ready = ready != 0 ? 1 : 0;
  AV_UNLOCK();
}

int32_t av_renderer_is_ready(void) {
  AV_LOCK();
  int32_t ready = g_renderer_ready;
  AV_UNLOCK();
  return ready;
}

static int32_t camera_is_valid(const av_camera *camera) {
  return camera != NULL && camera->scale > 0.0f &&
         isfinite(camera->scale) && isfinite(camera->ox) &&
         isfinite(camera->oy) && isfinite(camera->yaw) &&
         isfinite(camera->pitch) && isfinite(camera->distance) &&
         isfinite(camera->tx) && isfinite(camera->ty) &&
         isfinite(camera->viewport_width) && camera->viewport_width > 0.f &&
         isfinite(camera->viewport_height) && camera->viewport_height > 0.f &&
         isfinite(camera->pixels_per_metre) && camera->pixels_per_metre > 0.f &&
         isfinite(camera->center_x) && isfinite(camera->center_y) &&
         camera->viewport_revision >= 0;
}

int64_t av_camera_stage(const av_camera *camera) {
  if (!camera_is_valid(camera)) return -1;
  AV_LOCK();
  g_camera = *camera;
  int64_t seq = ++g_camera_seq;
  AV_UNLOCK();
  return seq;
}

int64_t av_camera_acquire(av_camera *out) {
  if (out == NULL) return -1;
  AV_LOCK();
  if (g_camera_seq == g_camera_consumed) {
    AV_UNLOCK();
    return 0;
  }
  *out = g_camera;
  g_camera_consumed = g_camera_seq;
  int64_t seq = g_camera_consumed;
  AV_UNLOCK();
  return seq;
}

void av_bridge_reset(void) {
  AV_LOCK();
  g_back_count = 0;
  g_seq = 0;
  g_consumed = 0;
  g_staged_at_ms = 0;
  g_renderer_ready = 0;
  memset(&g_camera, 0, sizeof(g_camera));
  g_camera_seq = 0;
  g_camera_consumed = 0;
  memset(&g_metrics, 0, sizeof(g_metrics));
  AV_UNLOCK();
}
