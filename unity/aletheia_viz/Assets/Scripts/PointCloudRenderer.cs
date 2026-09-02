using UnityEngine;
using UnityEngine.Rendering;

namespace Aletheia.Viz
{
    /// <summary>
    /// Draws the point cloud straight from a GPU buffer — one draw call, no
    /// GameObjects, no per-point CPU work per frame. Buffer is allocated once
    /// at the stress ceiling and reused; a new frame overwrites it
    /// (latest-wins). Works for 2D (float2, z=0) and 3D (float3).
    /// </summary>
    [RequireComponent(typeof(MeshRenderer))]
    public sealed class PointCloudRenderer : MonoBehaviour
    {
        [SerializeField] private Shader pointShader;
        // The web mobile HMI draws each laser sample as a 0.82 map-pixel
        // radius square.  Keep the same source-map calibration here; it is
        // converted to metres from the map descriptor at runtime.
        [SerializeField] private float pointSizeMetres = 0.082f;
        [SerializeField] private Color color = new(0.106f, 0.639f, 0.722f); // #1BA3B8

        private const int MaxPoints = 262144;

        private Material _material;
        private GraphicsBuffer _buffer;
        private int _pointCount;
        private int _floatsPerPoint = 2;
        private Bounds _bounds;
        private float[] _staging;
        private bool _visible = true;
        private static readonly int CanvasOffsetId = Shader.PropertyToID("_CanvasOffset");

        // World placement, set from the map descriptor.
        private Vector3 _origin = Vector3.zero;

        private void Awake()
        {
            // `pointShader` is serialized in Viz.unity so the iOS player
            // includes it. Shader.Find remains a development fallback only.
            var shader = pointShader ?? Shader.Find("Aletheia/PointCloudUnlit");
            if (shader == null)
            {
                Debug.LogError("[UnityViz] Point-cloud shader is unavailable; disabling cloud layer.");
                enabled = false;
                return;
            }
            _material = new Material(shader);
            _buffer = new GraphicsBuffer(GraphicsBuffer.Target.Structured,
                MaxPoints * 3, sizeof(float));
            _bounds = new Bounds(Vector3.zero, Vector3.one * 10000f);
        }

        public void SetVisible(bool v) => _visible = v;

        public void ConfigureFromMap(in VizMap map)
        {
            _origin = new Vector3(0f, 0f, 0f); // points already carry world x/y
            // Frontend mobile: pointRadius = 0.82 source-map pixels. The
            // procedural point-size property is a *diameter* in world metres,
            // so preserve the visual reference for every map resolution.
            pointSizeMetres = Mathf.Max(0.001f, map.res * 1.64f);
        }

        public void SetPointSize(float metres) => pointSizeMetres = Mathf.Max(0.001f, metres);

        /// <summary>Uploads one freshly acquired frame. `floats` length must be
        /// pointCount * floatsPerPoint.</summary>
        public void Upload(float[] floats, int floatCount, int floatsPerPoint)
        {
            if (!enabled || _buffer == null || floats == null || floatsPerPoint < 2)
                return;
            if (floatCount <= 0 || floatCount > floats.Length ||
                floatCount % floatsPerPoint != 0)
                return;

            _floatsPerPoint = floatsPerPoint;
            // Defense in depth: NativeCloudBridge rejects an oversized frame,
            // but the renderer must never issue a GPU upload beyond the fixed
            // MaxPoints allocation even if another caller invokes Upload.
            _pointCount = Mathf.Min(floatCount / floatsPerPoint, MaxPoints);
            if (_pointCount <= 0) return;

            // Pack into xyz regardless of source layout so the shader is uniform.
            if (_staging == null || _staging.Length < _pointCount * 3)
                _staging = new float[_pointCount * 3];

            if (floatsPerPoint == 3)
            {
                System.Array.Copy(floats, _staging, _pointCount * 3);
            }
            else
            {
                for (int i = 0; i < _pointCount; i++)
                {
                    _staging[i * 3 + 0] = floats[i * 2 + 0];
                    _staging[i * 3 + 1] = 0f; // y-up height; 2D cloud is flat
                    _staging[i * 3 + 2] = floats[i * 2 + 1];
                }
            }
            _buffer.SetData(_staging, 0, 0, _pointCount * 3);
        }

        public int PointCount => _pointCount;

        private void OnRenderObject()
        {
            if (!_visible || _pointCount == 0 || _material == null || _buffer == null) return;
            _material.SetBuffer("_Points", _buffer);
            _material.SetInt("_Stride", 3);
            _material.SetFloat("_PointSize", pointSizeMetres);
            _material.SetColor("_Color", color);
            // DrawProcedural does not inherit this component's Transform.
            // Feed the shared MapCanvas translation explicitly so GPU points
            // move exactly with the occupancy quad and robot marker.
            _material.SetVector(CanvasOffsetId, transform.parent == null
                ? Vector3.zero
                : transform.parent.localPosition);
            _material.SetPass(0);
            // Each source point is expanded into two triangles in the vertex
            // shader. Unlike MeshTopology.Points + PSIZE this is supported by
            // Metal in an embedded Unity runtime on physical iOS devices.
            Graphics.DrawProceduralNow(MeshTopology.Triangles, _pointCount * 6, 1);
        }

        private void OnDestroy()
        {
            _buffer?.Dispose();
            if (_material != null) Destroy(_material);
        }
    }
}
