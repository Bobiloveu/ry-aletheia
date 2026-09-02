using System;
using System.Runtime.InteropServices;
using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// Managed view of the native <c>aletheia_viz_bridge</c> staging buffer —
    /// the single high-throughput path from the Flutter data layer.
    ///
    /// Contract: exactly one pending frame (latest-wins). No history, no JSON,
    /// no per-point marshalling. The float buffer here is allocated once and
    /// reused; <see cref="TryAcquire"/> does one bulk copy from native.
    /// </summary>
    public static class NativeCloudBridge
    {
#if UNITY_IOS && !UNITY_EDITOR
        // The bridge lives in Aletheia's already-embedded CocoaPods framework
        // rather than the app executable. `__Internal` only searches the
        // executable's export table, which is intentionally unavailable to a
        // sibling framework in an iOS release IPA.
        private const string Dll = "@rpath/aletheia_visualization.framework/aletheia_visualization";
#else
        private const string Dll = "aletheia_viz_bridge";
#endif

        // Mirror of AV_MAX_FLOATS in aletheia_viz_bridge.h.
        public const int MaxFloats = 262144 * 3;

        [DllImport(Dll)]
        private static extern long av_cloud_acquire(
            float[] outBuf, int outCapacity, out int outFloatCount, out int outLayout);

        [DllImport(Dll)]
        private static extern long av_cloud_age_ms();

        [DllImport(Dll)]
        private static extern long av_camera_acquire(out AvCamera camera);

        [DllImport(Dll)]
        private static extern void av_metrics_report(ref AvMetrics m);

        [DllImport(Dll)]
        private static extern void av_bridge_reset();

        [DllImport(Dll)]
        private static extern void av_renderer_set_ready(int ready);

        [StructLayout(LayoutKind.Sequential)]
        public struct AvMetrics
        {
            public float render_fps;
            public float frame_ms_p50;
            public float frame_ms_p95;
            public int last_point_count;
            public long cloud_seq;
        }

        /// <summary>Binary-compatible with <c>av_camera</c>.</summary>
        [StructLayout(LayoutKind.Sequential)]
        private struct AvCamera
        {
            public float scale;
            public float ox;
            public float oy;
            public float yaw;
            public float pitch;
            public float distance;
            public float tx;
            public float ty;
            public long owner;
            public float viewport_width;
            public float viewport_height;
            public float pixels_per_metre;
            public float center_x;
            public float center_y;
            public long viewport_revision;
        }

        private static readonly float[] Scratch = new float[MaxFloats];

        /// <summary>Last acquired sequence, or 0 if none yet.</summary>
        public static long LastSeq { get; private set; }

        /// <summary>
        /// Reads the newest Flutter map gesture intent. This is deliberately
        /// independent from the point-cloud payload: it is only eight scalars
        /// and is consumed at most once per Unity frame.
        /// </summary>
        public static bool TryAcquireCamera(out VizCameraMsg camera, out long owner)
        {
            camera = default;
            owner = -1;
            try
            {
                long seq = av_camera_acquire(out AvCamera staged);
                if (seq <= 0) return false;
                owner = staged.owner;
                if (staged.scale <= 0f ||
                    float.IsNaN(staged.scale) || float.IsInfinity(staged.scale) ||
                    float.IsNaN(staged.ox) || float.IsInfinity(staged.ox) ||
                    float.IsNaN(staged.oy) || float.IsInfinity(staged.oy))
                {
                    return false;
                }
                camera = new VizCameraMsg
                {
                    scale = staged.scale,
                    ox = staged.ox,
                    oy = staged.oy,
                    yaw = staged.yaw,
                    pitch = staged.pitch,
                    distance = staged.distance,
                    tx = staged.tx,
                    ty = staged.ty,
                    viewportWidth = staged.viewport_width,
                    viewportHeight = staged.viewport_height,
                    pixelsPerMetre = staged.pixels_per_metre,
                    centerX = staged.center_x,
                    centerY = staged.center_y,
                    viewportRevision = staged.viewport_revision,
                };
                return true;
            }
            catch (DllNotFoundException)
            {
                return false;
            }
            catch (EntryPointNotFoundException)
            {
                // Permits an older native plugin to use the low-frequency
                // UnitySendMessage fallback without aborting the render loop.
                return false;
            }
        }

        /// <summary>
        /// Copies the pending frame into <paramref name="points"/> (a reused
        /// caller buffer). Returns true only when a new frame was present and
        /// it is fresh enough (native age &lt;= <paramref name="maxAgeMs"/>).
        /// </summary>
        public static bool TryAcquire(ref float[] points, out int floatCount,
            out int floatsPerPoint, long maxAgeMs = 100)
        {
            floatCount = 0;
            floatsPerPoint = 2;
            long seq;
            try
            {
                seq = av_cloud_acquire(Scratch, Scratch.Length,
                    out int fc, out int layout);
                if (seq <= 0) return false;
                if (av_cloud_age_ms() > maxAgeMs) { LastSeq = seq; return false; }
                if (fc <= 0 || fc > Scratch.Length ||
                    (layout != 2 && layout != 3) || fc % layout != 0 ||
                    fc / layout > 262144)
                {
                    Debug.LogWarning($"[UnityViz] rejected invalid cloud frame: floats={fc}, layout={layout}");
                    LastSeq = seq;
                    return false;
                }
                floatCount = fc;
                floatsPerPoint = layout;
            }
            catch (DllNotFoundException)
            {
                return false;
            }
            catch (EntryPointNotFoundException)
            {
                // The iOS host is intentionally renderer-optional during
                // migration. A missing ABI entry must not abort LateUpdate.
                return false;
            }

            if (points == null || points.Length < floatCount)
                points = new float[Mathf.Max(floatCount, 1)];
            Array.Copy(Scratch, points, floatCount);
            LastSeq = seq;
            return true;
        }

        public static void ReportMetrics(float fps, float p50, float p95,
            int pointCount)
        {
            var m = new AvMetrics
            {
                render_fps = fps,
                frame_ms_p50 = p50,
                frame_ms_p95 = p95,
                last_point_count = pointCount,
                cloud_seq = LastSeq,
            };
            try { av_metrics_report(ref m); }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }

        public static void Reset()
        {
            LastSeq = 0;
            try { av_bridge_reset(); }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }

        /// <summary>Marks the scene message target as available to Flutter.</summary>
        public static void SetRendererReady(bool ready)
        {
            try { av_renderer_set_ready(ready ? 1 : 0); }
            catch (DllNotFoundException e)
            {
                Debug.LogError($"[UnityViz] native renderer bridge library missing: {e.Message}");
            }
            // Readiness is diagnostic only. A renderer build that has not
            // embedded the bridge framework must not abort VizRoot.Start().
            catch (EntryPointNotFoundException e)
            {
                Debug.LogError($"[UnityViz] native renderer bridge entry missing: {e.Message}");
            }
        }
    }
}
