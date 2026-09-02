/* Android-only JNI shim so the Kotlin plugin can read render metrics that
 * Unity wrote into the shared aletheia_viz_bridge buffer. */
#include <jni.h>

#include "aletheia_viz_bridge.h"

JNIEXPORT jdoubleArray JNICALL
Java_com_ryaletheia_aletheia_1visualization_NativeBridge_readMetrics(
    JNIEnv *env, jobject thiz) {
  (void)thiz;
  av_metrics m;
  if (av_metrics_read(&m) != 0) {
    return NULL;
  }
  jdoubleArray out = (*env)->NewDoubleArray(env, 5);
  if (out == NULL) return NULL;
  jdouble vals[5] = {
      (jdouble)m.render_fps, (jdouble)m.frame_ms_p50, (jdouble)m.frame_ms_p95,
      (jdouble)m.last_point_count, (jdouble)m.cloud_seq};
  (*env)->SetDoubleArrayRegion(env, out, 0, 5, vals);
  return out;
}

JNIEXPORT jboolean JNICALL
Java_com_ryaletheia_aletheia_1visualization_NativeBridge_isRendererReady(
    JNIEnv *env, jobject thiz) {
  (void)env;
  (void)thiz;
  return av_renderer_is_ready() != 0 ? JNI_TRUE : JNI_FALSE;
}
