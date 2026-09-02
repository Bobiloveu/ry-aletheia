using System;
using System.Collections;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// The static occupancy raster as one unlit textured quad, placed in world
    /// metres. Updated only on map switch — never per pose/cloud frame.
    /// </summary>
    public sealed class OccupancyMap : MonoBehaviour
    {
        [SerializeField] private MeshRenderer quad;
        [SerializeField] private Material occupancyMaterial;

        private Texture2D _texture;
        private Material _material;
        // This shader deliberately exposes `_BaseMap` (rather than Unity's
        // legacy `_MainTex`). `Material.mainTexture` only targets the latter
        // unless a shader declares a main-texture attribute, so it silently
        // left the occupancy material on its empty default texture in the iOS
        // player while the cloud/grid continued to render.
        private static readonly int BaseMapId = Shader.PropertyToID("_BaseMap");

        private void Awake()
        {
            if (!EnsureMaterial()) enabled = false;
        }

        /// <summary>
        /// Kept separate from <see cref="Awake"/> so the full-resolution
        /// fixture validator exercises exactly the same texture path as the
        /// player.  It also makes a delayed scene attachment recoverable
        /// without creating a second renderer or touching any data source.
        /// </summary>
        private bool EnsureMaterial()
        {
            if (_material != null) return true;
            if (quad == null) quad = GetComponent<MeshRenderer>();
            if (quad == null || occupancyMaterial == null)
            {
                Debug.LogError("[Viz] Occupancy map material is not configured.");
                return false;
            }
            // This material is serialized in the scene, which makes its shader
            // an explicit iOS player dependency. `Shader.Find` would allow
            // IL2CPP/URP stripping to remove the map shader from the framework.
            _material = new Material(occupancyMaterial);
            quad.sharedMaterial = _material;
            return true;
        }

        public void Apply(in VizMap map, byte[] png)
        {
            ApplyLayout(map);
            if (png != null && png.Length > 0) ApplyPng(png);
        }

        /// <summary>
        /// Applies only world placement. This is intentionally separate from
        /// texture decoding so a large map can become visible through the
        /// asynchronous file path without blocking Unity's first UI frame.
        /// </summary>
        public void ApplyLayout(in VizMap map)
        {
            if (!EnsureMaterial()) return;

            // Unity's primitive Quad is authored in its *local XY* plane. The
            // scene rotates it +90° around X so local Y becomes map-world Z.
            // Scaling local Z here would do nothing because every Quad vertex
            // has z = 0; that previously collapsed a tall occupancy image to
            // a one-metre horizontal strip on device. Scale before rotation so
            // the entire raster occupies the same map-world canvas as the
            // grid, cloud and robot.
            transform.localScale = new Vector3(map.WorldWidth, map.WorldHeight, 1f);
            var c = map.WorldCenter;
            // OccupancyMap is a child of VizRoot/MapCanvas.  Keep placement
            // local so moving the canvas during a pan moves this exact raster
            // together with the grid, robot and point cloud.
            transform.localPosition = new Vector3(c.x, -0.001f, c.y);
        }

        public void ApplyPng(byte[] png)
        {
            if (!EnsureMaterial() || png == null || png.Length == 0) return;
            var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!texture.LoadImage(png, markNonReadable: true))
            {
                Destroy(texture);
                Debug.LogWarning("[UnityViz] occupancy PNG could not be decoded.");
                return;
            }
            ApplyTexture(texture);
        }

        /// <summary>
        /// Loads an unchanged PNG from the Flutter app's temporary sandbox.
        ///
        /// Do not use <c>UnityWebRequest</c> for a local application path
        /// here.  Under Unity-as-a-Library on iOS, its file-scheme request is
        /// evaluated by the embedded framework rather than the host process
        /// and can fail silently even though Flutter just staged the file in
        /// the shared app container.  Plain managed file IO has the same
        /// sandbox identity as the host and is deterministic.  The file read
        /// happens on the worker pool; only Unity's required texture decode
        /// runs on the rendering thread.
        /// </summary>
        public IEnumerator ApplyFileAsync(string pngPath)
        {
            if (!EnsureMaterial() || string.IsNullOrEmpty(pngPath)) yield break;
            if (!File.Exists(pngPath))
            {
                Debug.LogWarning($"[UnityViz] occupancy PNG path does not exist: {pngPath}");
                yield break;
            }

            var read = Task.Run(() => File.ReadAllBytes(pngPath));
            while (!read.IsCompleted) yield return null;
            if (read.IsCanceled || read.IsFaulted)
            {
                Debug.LogWarning($"[UnityViz] occupancy PNG file read failed: {pngPath}");
                yield break;
            }
            if (read.Result == null || read.Result.Length == 0)
            {
                Debug.LogWarning($"[UnityViz] occupancy PNG file is empty: {pngPath}");
                yield break;
            }

            ApplyPng(read.Result);
            if (HasBoundRaster)
            {
                Debug.Log($"[UnityViz] occupancy raster bound {RasterSize.x}x{RasterSize.y}");
            }
        }

        private void ApplyTexture(Texture2D texture)
        {
            if (texture == null || _material == null) return;
            texture.filterMode = FilterMode.Point;
            texture.wrapMode = TextureWrapMode.Clamp;
            var previous = _texture;
            _texture = texture;
            _material.SetTexture(BaseMapId, _texture);
            if (previous != null && previous != _texture) Destroy(previous);
        }

        public void SetVisible(bool v) => quad.enabled = v;

        /// <summary>Editor/device diagnostic invariant for the exact shader
        /// field used by the occupancy pass. It does not expose map data or
        /// change rendering behaviour.</summary>
        public bool HasBoundRaster =>
            _texture != null && _material != null &&
            _material.GetTexture(BaseMapId) == _texture;

        public Vector2Int RasterSize => _texture == null
            ? Vector2Int.zero
            : new Vector2Int(_texture.width, _texture.height);

        private void OnDestroy()
        {
            if (_texture != null) Destroy(_texture);
            if (_material != null) Destroy(_material);
        }
    }
}
