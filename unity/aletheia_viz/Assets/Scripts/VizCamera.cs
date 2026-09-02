using UnityEngine;

namespace Aletheia.Viz
{
    /// <summary>
    /// Scene camera for the embedded renderer. Flutter owns the complete 2D
    /// viewport. This class never derives a projection from Camera.pixelWidth
    /// or Camera.pixelHeight: an embedded Android SurfaceView can retain an
    /// intermediate card/fullscreen buffer during a route transition.
    /// </summary>
    [RequireComponent(typeof(Camera))]
    public sealed class VizCamera : MonoBehaviour
    {
        [SerializeField] private Material gridMaterial;
        private static readonly float[] GridSteps =
            { 0.25f, 0.5f, 1f, 2f, 5f, 10f, 20f };

        private Camera _cam;
        private VizViewMode _mode = VizViewMode.TwoD;
        private VizMap _map;
        private Transform _mapCanvas;
        private Vector2 _target;
        private float _viewportWidth;
        private float _viewportHeight;
        private float _pixelsPerMetre;
        private long _lastViewportRevision = -1;
        private bool _hasViewport;

        // 3D state is separate from the fixed 2D map projection contract.
        private float _yaw, _pitch = 0.6f, _distance = 20f;

        /// <summary>Pure projection math, kept public for editor validation.</summary>
        public readonly struct Projection
        {
            public Projection(float aspect, float orthographicSize)
            {
                Aspect = aspect;
                OrthographicSize = orthographicSize;
            }

            public readonly float Aspect;
            public readonly float OrthographicSize;
        }

        public static Projection ProjectionFor(float width, float height, float pixelsPerMetre)
        {
            float safeWidth = Mathf.Max(width, 1f);
            float safeHeight = Mathf.Max(height, 1f);
            float safePixelsPerMetre = Mathf.Max(pixelsPerMetre, 0.0001f);
            return new Projection(safeWidth / safeHeight,
                safeHeight / (2f * safePixelsPerMetre));
        }

        private void Awake()
        {
            _cam = GetComponent<Camera>();
            _cam.clearFlags = CameraClearFlags.SolidColor;
            _cam.backgroundColor = new Color(0.965f, 0.976f, 0.973f);
            _cam.nearClipPlane = 0.05f;
            _cam.farClipPlane = 2000f;
        }

        public void ConfigureFromMap(in VizMap map)
        {
            _map = map;
            // Camera packets travel on a latest-wins native bridge and can
            // legitimately arrive one frame before the UnitySendMessage map
            // payload is applied. Retain that Flutter-owned centre instead of
            // snapping it back to map centre during the async map bind.
            if (!_hasViewport) _target = map.WorldCenter;
            ApplyTransform();
        }

        public void SetMapCanvas(Transform mapCanvas) => _mapCanvas = mapCanvas;

        public void SetViewMode(VizViewMode mode)
        {
            _mode = mode;
            _cam.orthographic = mode == VizViewMode.TwoD;
            ApplyTransform();
        }

        /// <summary>
        /// Flutter calculates and stages the first pose centre before this
        /// compatibility notification reaches Unity. Never overwrite its
        /// viewport with a second native camera decision.
        /// </summary>
        public void FocusInitialPose(in VizPose pose) { }

        public void SetCamera(in VizCameraMsg m)
        {
            if (_mode == VizViewMode.TwoD)
            {
                if (!ViewportIsValid(m) || m.viewportRevision < _lastViewportRevision)
                    return;

                _lastViewportRevision = m.viewportRevision;
                _viewportWidth = m.viewportWidth;
                _viewportHeight = m.viewportHeight;
                _pixelsPerMetre = m.pixelsPerMetre;
                _target = new Vector2(m.centerX, m.centerY);
                _hasViewport = true;
            }
            else
            {
                _yaw = m.yaw;
                _pitch = Mathf.Clamp(m.pitch, 0.15f, 1.45f);
                _distance = Mathf.Max(m.distance, 1f);
                _target = new Vector2(_map.WorldCenter.x + m.tx,
                    _map.WorldCenter.y + m.ty);
            }
            ApplyTransform();
        }

        private static bool ViewportIsValid(in VizCameraMsg m)
        {
            return m.viewportWidth > 0f && m.viewportHeight > 0f &&
                m.pixelsPerMetre > 0f &&
                !float.IsNaN(m.viewportWidth) && !float.IsInfinity(m.viewportWidth) &&
                !float.IsNaN(m.viewportHeight) && !float.IsInfinity(m.viewportHeight) &&
                !float.IsNaN(m.pixelsPerMetre) && !float.IsInfinity(m.pixelsPerMetre) &&
                !float.IsNaN(m.centerX) && !float.IsInfinity(m.centerX) &&
                !float.IsNaN(m.centerY) && !float.IsInfinity(m.centerY);
        }

        private void ApplyTransform()
        {
            if (_mode == VizViewMode.TwoD)
            {
                // Do not draw a guessed 2D pose before Flutter publishes its
                // first complete logical viewport.
                if (!_hasViewport) return;

                Projection projection = ProjectionFor(
                    _viewportWidth, _viewportHeight, _pixelsPerMetre);
                _cam.orthographic = true;
                _cam.aspect = projection.Aspect;
                _cam.orthographicSize = projection.OrthographicSize;
                if (_mapCanvas != null)
                    _mapCanvas.localPosition = new Vector3(-_target.x, 0f, -_target.y);
                transform.position = new Vector3(0f, 100f, 0f);
                transform.rotation = Quaternion.Euler(90f, 0f, 0f);
                PushGridForPixelsPerMetre(_pixelsPerMetre);
                return;
            }

            if (_mapCanvas != null) _mapCanvas.localPosition = Vector3.zero;
            var target = new Vector3(_target.x, 0f, _target.y);
            var offset = new Vector3(
                Mathf.Sin(_yaw) * Mathf.Cos(_pitch), Mathf.Sin(_pitch),
                Mathf.Cos(_yaw) * Mathf.Cos(_pitch)) * _distance;
            transform.position = target + offset;
            transform.LookAt(target);
            PushGridForPixelsPerMetre(_pixelsPerMetre > 0f ? _pixelsPerMetre : 1f);
        }

        private void PushGridForPixelsPerMetre(float pixelsPerMetre)
        {
            if (gridMaterial == null) return;
            float minor = GridSteps[GridSteps.Length - 1];
            foreach (float step in GridSteps)
            {
                if (pixelsPerMetre * step >= 26f) { minor = step; break; }
            }
            gridMaterial.SetFloat("_Minor", minor);
            gridMaterial.SetFloat("_Major", minor * 5f);
        }
    }
}
