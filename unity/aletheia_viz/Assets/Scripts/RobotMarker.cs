using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// Vehicle footprint + heading from the live pose. Size comes from the
    /// active vehicle model in the map descriptor (never a fixed pixel icon).
    /// The 2D marker is a small layered HMI symbol: charcoal chassis, warm
    /// deck and a forward indicator. It stays legible on a white occupancy
    /// map without turning the vehicle into the old opaque black rectangle.
    /// </summary>
    public sealed class RobotMarker : MonoBehaviour
    {
        [SerializeField] private Transform footprint; // legacy quad, hidden at runtime
        [SerializeField] private Transform body3D;    // primitive box, hidden in 2D
        [SerializeField] private Material hullMaterial;
        [SerializeField] private Material deckMaterial;
        [SerializeField] private Material headingMaterial;

        private VizMap _map;
        private bool _has;
        private MeshRenderer _hull;
        private MeshRenderer _deck;
        private MeshRenderer _heading;
        private readonly Material[] _fallbackMaterials = new Material[3];

        private void Awake()
        {
            EnsureVisuals();
        }

        public void ConfigureFromMap(in VizMap map)
        {
            _map = map;
            EnsureVisuals();
            Build2DMarker(Mathf.Max(map.vwid, 0.05f), Mathf.Max(map.vlen, 0.05f));
            if (body3D != null)
            {
                body3D.localScale = new Vector3(map.vwid, 0.6f, map.vlen);
                var renderer = body3D.GetComponent<MeshRenderer>();
                if (renderer != null && hullMaterial != null)
                    renderer.sharedMaterial = hullMaterial;
            }
        }

        public void SetPose(in VizPose p)
        {
            _has = true;
            // Map yaw: Flutter draws the vehicle rotated by (pi/2 - yaw). In
            // world XZ, forward is +Z; rotate about Y by -yaw so heading matches.
            // VizRoot/MapCanvas owns the world-to-screen translation.  Pose
            // remains in immutable map coordinates, rather than being written
            // into a separate camera/world transform.
            transform.localPosition = new Vector3(p.x, 0f, p.y);
            transform.localRotation = Quaternion.Euler(0f, -p.yaw * Mathf.Rad2Deg + 90f, 0f);
        }

        public void SetViewMode(VizViewMode mode)
        {
            if (body3D != null) body3D.gameObject.SetActive(mode == VizViewMode.ThreeD);
            Set2DVisible(mode == VizViewMode.TwoD);
        }

        public void SetVisible(bool v) => gameObject.SetActive(v && _has);

        private void EnsureVisuals()
        {
            if (footprint != null) footprint.gameObject.SetActive(false);
            if (_hull != null) return;

            _hull = CreateLayer("VehicleHull", MaterialFor(0, hullMaterial, new Color(0.075f, 0.11f, 0.12f)));
            _deck = CreateLayer("VehicleDeck", MaterialFor(1, deckMaterial, new Color(0.886f, 0.706f, 0.431f)));
            _heading = CreateLayer("VehicleHeading", MaterialFor(2, headingMaterial, new Color(0.09f, 0.18f, 0.19f)));
        }

        private MeshRenderer CreateLayer(string name, Material material)
        {
            var go = new GameObject(name, typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            var renderer = go.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return renderer;
        }

        private Material MaterialFor(int index, Material serialized, Color fallbackColor)
        {
            if (serialized != null) return serialized;
            var shader = Shader.Find("Aletheia/RobotMarkerUnlit");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            if (shader == null)
            {
                Debug.LogError("[UnityViz] Robot marker shader is unavailable.");
                return null;
            }
            var material = new Material(shader) { color = fallbackColor };
            _fallbackMaterials[index] = material;
            return material;
        }

        private void Build2DMarker(float width, float length)
        {
            // Positive local Z is the car's forward direction. The front
            // chamfer makes heading readable before the colour cue is needed.
            float halfWidth = width * 0.5f;
            float halfLength = length * 0.5f;
            float nose = Mathf.Min(length * 0.16f, width * 0.28f);
            SetPolygon(_hull, "VehicleHullMesh", new[]
            {
                new Vector2(-halfWidth, -halfLength),
                new Vector2( halfWidth, -halfLength),
                new Vector2( halfWidth, halfLength - nose),
                new Vector2( halfWidth * 0.56f, halfLength),
                new Vector2(-halfWidth * 0.56f, halfLength),
                new Vector2(-halfWidth, halfLength - nose),
            }, 0.016f);

            float deckHalfWidth = width * 0.31f;
            float deckHalfLength = length * 0.34f;
            float deckCentre = -length * 0.025f;
            SetPolygon(_deck, "VehicleDeckMesh", new[]
            {
                new Vector2(-deckHalfWidth, deckCentre - deckHalfLength),
                new Vector2( deckHalfWidth, deckCentre - deckHalfLength),
                new Vector2( deckHalfWidth, deckCentre + deckHalfLength),
                new Vector2(-deckHalfWidth, deckCentre + deckHalfLength),
            }, 0.021f);

            // A short high-contrast chevron on the deck is a stable forward
            // cue even when the real vehicle is only a few display pixels.
            float markWidth = Mathf.Max(width * 0.075f, 0.012f);
            float markBack = length * 0.08f;
            float markFront = length * 0.29f;
            SetPolygon(_heading, "VehicleHeadingMesh", new[]
            {
                new Vector2(-markWidth, markBack),
                new Vector2( markWidth, markBack),
                new Vector2( markWidth, markFront - markWidth),
                new Vector2(0f, markFront),
                new Vector2(-markWidth, markFront - markWidth),
            }, 0.026f);
        }

        private static void SetPolygon(MeshRenderer renderer, string name, Vector2[] outline, float y)
        {
            if (renderer == null || outline == null || outline.Length < 3) return;
            var old = renderer.GetComponent<MeshFilter>().sharedMesh;
            var mesh = new Mesh { name = name };
            var vertices = new Vector3[outline.Length];
            for (int i = 0; i < outline.Length; i++)
                vertices[i] = new Vector3(outline[i].x, y, outline[i].y);
            var triangles = new int[(outline.Length - 2) * 3];
            for (int i = 0; i < outline.Length - 2; i++)
            {
                triangles[i * 3] = 0;
                triangles[i * 3 + 1] = i + 1;
                triangles[i * 3 + 2] = i + 2;
            }
            mesh.vertices = vertices;
            mesh.triangles = triangles;
            mesh.RecalculateBounds();
            renderer.GetComponent<MeshFilter>().sharedMesh = mesh;
            if (old != null) Destroy(old);
        }

        private void Set2DVisible(bool visible)
        {
            if (_hull != null) _hull.enabled = visible;
            if (_deck != null) _deck.enabled = visible;
            if (_heading != null) _heading.enabled = visible;
        }

        private void OnDestroy()
        {
            foreach (var material in _fallbackMaterials)
                if (material != null) Destroy(material);
        }
    }
}
