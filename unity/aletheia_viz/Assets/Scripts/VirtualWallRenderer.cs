using System.Collections.Generic;
using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// Draws the static virtual-wall polylines supplied by Flutter as one
    /// lightweight mesh.  The geometry shares MapCanvas with the occupancy
    /// raster, point cloud and robot, so every camera pan/zoom is guaranteed
    /// to move all map layers together.
    /// </summary>
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public sealed class VirtualWallRenderer : MonoBehaviour
    {
        [SerializeField] private Shader wallShader;

        // At the web HMI's normal 16 m view this is a clear ~2 px line while
        // remaining much thinner than the old debug-only wall overlay.
        private const float WidthMetres = 0.075f;
        private const float Height = 0.008f;

        private MeshFilter _filter;
        private MeshRenderer _renderer;
        private Mesh _mesh;
        private Material _material;

        private void Awake()
        {
            _filter = GetComponent<MeshFilter>();
            _renderer = GetComponent<MeshRenderer>();
            _mesh = new Mesh { name = "AletheiaVirtualWalls" };
            _mesh.MarkDynamic();
            _filter.sharedMesh = _mesh;
            if (wallShader == null) wallShader = Shader.Find("Aletheia/VirtualWallUnlit");
            if (wallShader == null)
            {
                Debug.LogError("[UnityViz] Virtual-wall shader is not configured.");
                enabled = false;
                return;
            }
            _material = new Material(wallShader);
            _renderer.sharedMaterial = _material;
        }

        public void SetWalls(float[][] walls)
        {
            if (_mesh == null) return;
            var vertices = new List<Vector3>();
            var triangles = new List<int>();
            if (walls != null)
            {
                foreach (var wall in walls)
                    AddWall(wall, vertices, triangles);
            }

            _mesh.Clear();
            if (vertices.Count > 0)
            {
                _mesh.SetVertices(vertices);
                _mesh.SetTriangles(triangles, 0, true);
                _mesh.RecalculateBounds();
            }
            _renderer.enabled = vertices.Count > 0;
            Debug.Log($"[UnityViz] virtual walls applied segments={triangles.Count / 6}");
        }

        private static void AddWall(
            float[] wall,
            List<Vector3> vertices,
            List<int> triangles)
        {
            if (wall == null || wall.Length < 4) return;
            float halfWidth = WidthMetres * 0.5f;
            for (int i = 0; i + 3 < wall.Length; i += 2)
            {
                var a = new Vector2(wall[i], wall[i + 1]);
                var b = new Vector2(wall[i + 2], wall[i + 3]);
                var direction = b - a;
                if (direction.sqrMagnitude < 0.000001f) continue;
                var normal = new Vector2(-direction.y, direction.x).normalized * halfWidth;
                int index = vertices.Count;
                vertices.Add(new Vector3(a.x - normal.x, Height, a.y - normal.y));
                vertices.Add(new Vector3(a.x + normal.x, Height, a.y + normal.y));
                vertices.Add(new Vector3(b.x + normal.x, Height, b.y + normal.y));
                vertices.Add(new Vector3(b.x - normal.x, Height, b.y - normal.y));
                triangles.Add(index);
                triangles.Add(index + 1);
                triangles.Add(index + 2);
                triangles.Add(index);
                triangles.Add(index + 2);
                triangles.Add(index + 3);
            }
        }

        public void SetVisible(bool visible)
        {
            if (_renderer != null) _renderer.enabled = visible && _mesh != null && _mesh.vertexCount > 0;
        }

        private void OnDestroy()
        {
            if (_mesh != null) Destroy(_mesh);
            if (_material != null) Destroy(_material);
        }
    }
}
