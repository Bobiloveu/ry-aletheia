using System;
using System.Collections.Generic;
using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// The single entry point for messages from the Flutter host, hosted on the
    /// GameObject named <c>VizRoot</c>. The native plugin calls
    /// <see cref="OnHostMessage"/> with "<c>method</c>{json}" strings.
    ///
    /// This class does rendering orchestration only. It never opens a socket,
    /// calls a service, parses a robot payload or runs business logic — every
    /// value it sees was prepared by the Flutter data layer.
    /// </summary>
    public sealed class VizBridge : MonoBehaviour
    {
        [SerializeField] private VizCamera cam;
        [SerializeField] private OccupancyMap occupancy;
        [SerializeField] private PointCloudRenderer cloud;
        [SerializeField] private RobotMarker robot;
        [SerializeField] private VirtualWallRenderer virtualWalls;
        [SerializeField] private MeshRenderer grid;
        [SerializeField] private Transform mapCanvas;

        private VizMap _map;
        private bool _hasMap;
        private VizViewMode _mode = VizViewMode.TwoD;
        // The Flutter PlatformView ID that currently owns the process-wide
        // Unity renderer. A fullscreen route briefly overlaps its card and
        // fullscreen views; camera writes from the retired owner are ignored.
        private long _activeCameraOwner = -1;
        private readonly HashSet<string> _hiddenLayers = new();

        private float[] _cloudScratch;
        private readonly Queue<float> _frameMs = new();
        private float _metricsAccum;
        private Coroutine _pendingMapRasterLoad;
        private static readonly int GridMapOriginId = Shader.PropertyToID("_MapOrigin");
        private static readonly int GridMapSizeId = Shader.PropertyToID("_MapSize");

        private void Awake()
        {
            NotifyAndroidDiagnostic("VizBridge.Awake");
            // Match the mobile web renderer's single `world-stage`: map
            // raster, metre grid, point cloud and robot are siblings in one
            // movable canvas.  The camera no longer independently pans a
            // texture while telemetry remains in another coordinate space.
            // The runtime setup also upgrades existing exported scenes, so a
            // device build does not rely on editor-only scene regeneration.
            if (mapCanvas == null)
            {
                var canvas = new GameObject("MapCanvas");
                canvas.transform.SetParent(transform, false);
                mapCanvas = canvas.transform;
            }

            ReparentToCanvas(occupancy == null ? null : occupancy.transform);
            ReparentToCanvas(cloud == null ? null : cloud.transform);
            ReparentToCanvas(robot == null ? null : robot.transform);
            EnsureVirtualWallLayer();
            ReparentToCanvas(virtualWalls == null ? null : virtualWalls.transform);
            ReparentToCanvas(grid == null ? null : grid.transform);
            cam?.SetMapCanvas(mapCanvas);
        }

        private void ReparentToCanvas(Transform layer)
        {
            if (layer != null && layer.parent != mapCanvas)
                layer.SetParent(mapCanvas, true);
        }

        private void EnsureVirtualWallLayer()
        {
            if (virtualWalls != null) return;
            var layer = new GameObject("VirtualWalls", typeof(MeshFilter), typeof(MeshRenderer));
            layer.transform.SetParent(mapCanvas, false);
            virtualWalls = layer.AddComponent<VirtualWallRenderer>();
        }

        private void Start()
        {
            NotifyAndroidDiagnostic("VizBridge.Start.before-ready");
            // This is the first frame in which UnitySendMessage can reliably
            // target VizRoot. The Flutter host waits for this explicit signal
            // before it sends the map descriptor.
            NativeCloudBridge.SetRendererReady(true);
            NotifyAndroidSceneReady(true);
            NotifyAndroidDiagnostic("VizBridge.Start.ready");
            Debug.Log("[UnityViz] VizRoot.Start completed; renderer ready set");
        }

        private void OnDestroy()
        {
            NotifyAndroidDiagnostic("VizBridge.OnDestroy");
            NativeCloudBridge.SetRendererReady(false);
            NotifyAndroidSceneReady(false);
        }

        private static void NotifyAndroidSceneReady(bool ready)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using (var bridge = new AndroidJavaClass(
                    "com.ryaletheia.aletheia_visualization.UnityLifecycleBridge"))
                {
                    bridge.CallStatic(ready ? "markSceneReady" : "markSceneStopped");
                }
            }
            catch (Exception e)
            {
                // Android renderer availability is optional; never allow a
                // host-side diagnostic bridge to stop the map scene itself.
                Debug.LogWarning($"[UnityViz] Android scene-ready callback failed: {e.Message}");
            }
#endif
        }

        private static void NotifyAndroidDiagnostic(string stage)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using (var bridge = new AndroidJavaClass(
                    "com.ryaletheia.aletheia_visualization.UnityLifecycleBridge"))
                {
                    bridge.CallStatic("markDiagnostic", stage);
                }
            }
            catch
            {
                // A diagnostic must never perturb the renderer lifecycle.
            }
#endif
        }

        // ---- host -> Unity ------------------------------------------------

        public void OnHostMessage(string raw)
        {
            NotifyAndroidDiagnostic("VizBridge.OnHostMessage");
            if (string.IsNullOrEmpty(raw)) return;
            // Android/iOS host bridges use an SOH delimiter to keep method
            // names unambiguous when a payload contains JSON.  The previous
            // parser only searched for '{', leaving '\u0001' attached to the
            // method name (for example "loadMap\u0001"). That made every
            // switch case miss silently: Unity was running but never applied
            // the map, hence the black Android canvas.
            int separator = raw.IndexOf('\u0001');
            string method;
            string json;
            if (separator >= 0)
            {
                method = raw.Substring(0, separator);
                json = separator + 1 < raw.Length
                    ? raw.Substring(separator + 1)
                    : "{}";
            }
            else
            {
                // Compatibility with older hosts that concatenated the
                // method directly with its JSON object.
                int brace = raw.IndexOf('{');
                method = brace < 0 ? raw : raw.Substring(0, brace);
                json = brace < 0 ? "{}" : raw.Substring(brace);
            }

            try
            {
                switch (method)
                {
                    case "loadMap": LoadMap(json); break;
                    case "setPose": SetPose(JsonUtility.FromJson<VizPose>(json)); break;
                    case "setCamera": cam.SetCamera(JsonUtility.FromJson<VizCameraMsg>(json)); break;
                    case "activateSession": ActivateSession(json); break;
                    case "setViewMode": SetViewMode(raw.EndsWith("3d") ? VizViewMode.ThreeD : VizViewMode.TwoD); break;
                    case "setLayer": SetLayer(JsonUtility.FromJson<VizLayerMsg>(json)); break;
                    // Do not reset the process-wide FFI buffers here. Flutter
                    // can have already staged the replacement view's newest
                    // camera/cloud frame while Unity is acknowledging Start().
                    case "bridgeReady": break;
                    default: break;
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[Viz] bad host message '{method}': {e.Message}");
            }
        }

        private void ActivateSession(string json)
        {
            var session = JsonUtility.FromJson<SessionEnvelope>(json);
            _activeCameraOwner = session.owner;
        }

        private void LoadMap(string json)
        {
            // The PNG bytes ride as a base64 field to keep JsonUtility happy.
            var envelope = JsonUtility.FromJson<MapEnvelope>(json);
            _map = new VizMap
            {
                id = envelope.id, w = envelope.w, h = envelope.h,
                res = envelope.res, ox = envelope.ox, oy = envelope.oy,
                vlen = envelope.vlen, vwid = envelope.vwid,
            };
            // Configure geometry immediately, then decode a full-resolution
            // raster asynchronously from Flutter's temp sandbox. The legacy
            // base64 field remains only as a transport fallback for hosts that
            // cannot create the temporary file.
            occupancy.ApplyLayout(_map);
            ConfigureWorkspaceCanvas(_map);
            cam.ConfigureFromMap(_map);
            cloud.ConfigureFromMap(_map);
            robot.ConfigureFromMap(_map);
            virtualWalls?.SetWalls(ExtractWallPoints(envelope.walls));
            _hasMap = true;
            if (_pendingMapRasterLoad != null) StopCoroutine(_pendingMapRasterLoad);
            if (!string.IsNullOrEmpty(envelope.pngPath))
            {
                _pendingMapRasterLoad = StartCoroutine(
                    occupancy.ApplyFileAsync(envelope.pngPath));
                Debug.Log($"[UnityViz] map raster loading from path id={_map.id} size={_map.w}x{_map.h} res={_map.res}");
                return;
            }

            byte[] png = string.IsNullOrEmpty(envelope.png)
                ? Array.Empty<byte>()
                : Convert.FromBase64String(envelope.png);
            occupancy.ApplyPng(png);
            Debug.Log($"[UnityViz] map applied from legacy payload id={_map.id} size={_map.w}x{_map.h} res={_map.res}");
        }

        private void SetPose(VizPose p)
        {
            cam.FocusInitialPose(p);
            robot.SetPose(p);
            robot.SetVisible(!_hiddenLayers.Contains("robot"));
        }

        private void SetViewMode(VizViewMode mode)
        {
            _mode = mode;
            cam.SetViewMode(mode);
            robot.SetViewMode(mode);
        }

        private void SetLayer(VizLayerMsg m)
        {
            if (m.v) _hiddenLayers.Remove(m.layer); else _hiddenLayers.Add(m.layer);
            occupancy.SetVisible(!_hiddenLayers.Contains("occupancyMap"));
            if (grid != null) grid.enabled = !_hiddenLayers.Contains("grid");
            cloud.SetVisible(!_hiddenLayers.Contains("pointCloud"));
            robot.SetVisible(!_hiddenLayers.Contains("robot"));
            virtualWalls?.SetVisible(!_hiddenLayers.Contains("virtualWalls"));
        }

        /// <summary>
        /// Size the map workspace rather than leaving an effectively infinite
        /// dark grid behind the raster.  This is the Unity equivalent of the
        /// web HMI's white world-stage: a small, useful margin remains around
        /// every map edge so panning to a boundary never feels like falling
        /// off the canvas.
        /// </summary>
        private void ConfigureWorkspaceCanvas(in VizMap map)
        {
            if (grid == null) return;
            float marginX = Mathf.Max(8f, map.WorldWidth * 0.12f);
            float marginY = Mathf.Max(8f, map.WorldHeight * 0.08f);
            grid.transform.localScale = new Vector3(
                map.WorldWidth + marginX * 2f,
                map.WorldHeight + marginY * 2f,
                1f);
            var center = map.WorldCenter;
            // The web grid is a translucent reference layer *over* the
            // occupancy texture, not a background hidden by the opaque PNG.
            // Keep it below virtual walls (0.008) yet above the map quad
            // (-0.001) so it remains readable across the whole white canvas.
            grid.transform.localPosition = new Vector3(center.x, 0.001f, center.y);

            // The grid phase is expressed in immutable map coordinates, not
            // Unity world coordinates. VizCamera pans MapCanvas itself;
            // sampling `unity_ObjectToWorld` in the shader made grid lines
            // slide under the occupancy raster during a canvas drag.
            var material = grid.sharedMaterial;
            if (material != null)
            {
                material.SetVector(GridMapOriginId, new Vector4(center.x, center.y, 0f, 0f));
                material.SetVector(GridMapSizeId, new Vector4(
                    grid.transform.localScale.x, grid.transform.localScale.y, 0f, 0f));
            }
        }

        private static float[][] ExtractWallPoints(WallEnvelope[] walls)
        {
            if (walls == null || walls.Length == 0) return Array.Empty<float[]>();
            var result = new float[walls.Length][];
            for (int i = 0; i < walls.Length; i++) result[i] = walls[i].p;
            return result;
        }

        // ---- render loop ------------------------------------------------

        private void LateUpdate()
        {
            if (!_hasMap) return;

            // Pan/pinch takes the high-frequency scalar bridge directly into
            // the shared MapCanvas transform. It must run before other visual
            // layers so map, grid, wall, cloud and robot remain locked to the
            // exact same camera intent for this rendered frame.
            if (NativeCloudBridge.TryAcquireCamera(out VizCameraMsg camera,
                    out long owner) && owner == _activeCameraOwner)
            {
                cam.SetCamera(camera);
            }

            bool threeD = _mode == VizViewMode.ThreeD;
            if (NativeCloudBridge.TryAcquire(ref _cloudScratch, out int fc,
                    out int fpp, threeD ? 200 : 100))
            {
                cloud.Upload(_cloudScratch, fc, fpp);
            }

            ReportMetrics();
        }

        private void ReportMetrics()
        {
            float ms = Time.unscaledDeltaTime * 1000f;
            _frameMs.Enqueue(ms);
            if (_frameMs.Count > 120) _frameMs.Dequeue();

            _metricsAccum += Time.unscaledDeltaTime;
            if (_metricsAccum < 1f) return;
            _metricsAccum = 0f;

            var arr = _frameMs.ToArray();
            Array.Sort(arr);
            float p50 = arr[arr.Length / 2];
            float p95 = arr[Mathf.Clamp((int)(arr.Length * 0.95f), 0, arr.Length - 1)];
            float fps = 1000f / Mathf.Max(p50, 0.001f);
            NativeCloudBridge.ReportMetrics(fps, p50, p95, cloud.PointCount);
        }

        private void OnApplicationPause(bool paused)
        {
            // The host also drives pause() explicitly; this covers OS-level.
            if (paused) NativeCloudBridge.Reset();
        }

        [Serializable]
        private struct MapEnvelope
        {
            public string id, png, pngPath;
            public int w, h;
            public float res, ox, oy, vlen, vwid;
            public WallEnvelope[] walls;
        }

        [Serializable]
        private struct WallEnvelope
        {
            // [x0, y0, x1, y1, ...] in map world metres.
            public float[] p;
        }
    }
}
