#if UNITY_EDITOR
using System;
using UnityEditor;
using UnityEngine;

namespace Aletheia.Viz.EditorTools
{
    /// <summary>
    /// Headless guard for the Android fullscreen regression: projection math
    /// must be derived from the one Flutter logical viewport packet, not from
    /// an arbitrary Unity render-target size.
    /// </summary>
    public static class VizViewportValidation
    {
        [MenuItem("Aletheia/Validate Flutter-Owned Viewport Projection")]
        public static void ValidateFlutterOwnedViewportProjection()
        {
            var portrait = VizCamera.ProjectionFor(360f, 640f, 40f);
            var landscape = VizCamera.ProjectionFor(640f, 360f, 40f);

            AssertClose(portrait.Aspect, 0.5625f, "portrait aspect");
            AssertClose(portrait.OrthographicSize, 8f, "portrait ortho size");
            AssertClose(landscape.Aspect, 640f / 360f, "landscape aspect");
            AssertClose(landscape.OrthographicSize, 4.5f, "landscape ortho size");

            // One metre must occupy the same 40 logical pixels in both
            // layouts. This is the invariant that old Camera.pixelWidth-based
            // recomputation broke during the Android SurfaceView transition.
            AssertClose(2f * portrait.OrthographicSize * 40f, 640f,
                "portrait logical height");
            AssertClose(2f * landscape.OrthographicSize * 40f, 360f,
                "landscape logical height");
            Debug.Log("[VizValidation] Flutter-owned viewport projection passed.");
        }

        private static void AssertClose(float actual, float expected, string label)
        {
            if (Mathf.Abs(actual - expected) > 0.0001f)
                throw new InvalidOperationException($"Unexpected {label}: {actual}; expected {expected}.");
        }
    }
}
#endif
