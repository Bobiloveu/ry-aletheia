#if UNITY_EDITOR
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace Aletheia.Viz.EditorTools
{
    /// <summary>
    /// A repeatable, headless validation of the real full-resolution map
    /// supplied for mobile HMI review.  This is intentionally not a mock:
    /// it runs the same OccupancyMap material binding and PNG decoder used by
    /// the iOS player, without requiring a robot or an iPhone.
    /// </summary>
    public static class VizFixtureValidation
    {
        private const int ExpectedWidth = 3480;
        private const int ExpectedHeight = 10017;

        [MenuItem("Aletheia/Validate Full-Resolution Map Fixture")]
        public static void ValidateFullResolutionMapFixture()
        {
            var projectRoot = Directory.GetParent(Application.dataPath)!.FullName;
            var repositoryRoot = Directory.GetParent(Directory.GetParent(projectRoot)!.FullName)!.FullName;
            var fixturePath = Path.Combine(repositoryRoot, "mobile", "assets", "debug_ui", "sample_map.png");
            if (!File.Exists(fixturePath))
                throw new FileNotFoundException("Aletheia full-resolution map fixture is missing.", fixturePath);

            var mapObject = GameObject.CreatePrimitive(PrimitiveType.Quad);
            mapObject.name = "FixtureOccupancyMap";
            mapObject.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            UnityEngine.Object.DestroyImmediate(mapObject.GetComponent<Collider>());
            var occupancy = mapObject.AddComponent<OccupancyMap>();
            var serialized = new SerializedObject(occupancy);
            serialized.FindProperty("occupancyMaterial").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Material>("Assets/Materials/OccupancyMap.mat");
            serialized.ApplyModifiedPropertiesWithoutUndo();

            var stopwatch = Stopwatch.StartNew();
            var map = new VizMap
            {
                id = "full-resolution-fixture",
                w = ExpectedWidth,
                h = ExpectedHeight,
                res = 0.05f,
                ox = -111.57f,
                oy = -248.79f,
                vlen = 0.72f,
                vwid = 0.58f,
            };
            occupancy.ApplyLayout(map);
            // A Unity primitive Quad is local XY and is rotated into the XZ
            // map plane. Guard the real-device regression where map height
            // was accidentally assigned to its unused local Z axis, reducing
            // the full occupancy raster to a thin horizontal band.
            var expectedScale = new Vector3(map.WorldWidth, map.WorldHeight, 1f);
            if ((mapObject.transform.localScale - expectedScale).sqrMagnitude > 0.0001f)
                throw new InvalidOperationException(
                    $"Unexpected occupancy quad scale {mapObject.transform.localScale}; " +
                    $"expected {expectedScale} for the world-stage canvas.");
            // Drive the exact Unity-as-a-Library file transport path.  This
            // validates the shared-sandbox raster route rather than only the
            // legacy in-memory/base64 decoder.
            var load = occupancy.ApplyFileAsync(fixturePath);
            while (load.MoveNext())
            {
                if (stopwatch.Elapsed > TimeSpan.FromSeconds(10))
                    throw new TimeoutException("Full-resolution occupancy file load did not complete within 10 seconds.");
                Thread.Sleep(1);
            }
            stopwatch.Stop();

            if (!occupancy.HasBoundRaster)
                throw new InvalidOperationException("Occupancy raster did not bind to the _BaseMap material field.");
            if (occupancy.RasterSize != new Vector2Int(ExpectedWidth, ExpectedHeight))
                throw new InvalidOperationException(
                    $"Unexpected raster size {occupancy.RasterSize}; expected {ExpectedWidth}x{ExpectedHeight}.");

            var textureBytes = (long)ExpectedWidth * ExpectedHeight * 4;
            Debug.Log(
                $"[VizValidation] full map bound: {ExpectedWidth}x{ExpectedHeight}, " +
                $"png={new FileInfo(fixturePath).Length:N0} B, rgba≈{textureBytes / (1024f * 1024f):F1} MiB, " +
                $"decode+bind={stopwatch.ElapsedMilliseconds} ms, " +
                $"maxTextureSize={SystemInfo.maxTextureSize}.");
            UnityEngine.Object.DestroyImmediate(mapObject);
        }

        /// <summary>
        /// Exercises the exact fixed-capacity cloud upload used by live
        /// telemetry.  It intentionally includes the largest valid XY frame
        /// and an over-capacity caller input: both must remain bounded by the
        /// same 262,144 point GPU allocation without allocating a new buffer
        /// or issuing an out-of-range GraphicsBuffer upload.
        /// </summary>
        [MenuItem("Aletheia/Validate Point-Cloud Frame Bounds")]
        public static void ValidatePointCloudFrameBounds()
        {
            const int maxPoints = 262144;
            // Add the component while inactive so its serialized shader is in
            // place before Awake allocates the fixed GPU buffer. Shader.Find
            // is intentionally only a development fallback and is not a
            // reliable editor-batch asset inclusion mechanism.
            var mapObject = new GameObject("FixturePointCloud");
            mapObject.SetActive(false);
            mapObject.AddComponent<MeshRenderer>();
            var cloud = mapObject.AddComponent<PointCloudRenderer>();
            var serialized = new SerializedObject(cloud);
            serialized.FindProperty("pointShader").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Shader>("Assets/Shaders/PointCloudUnlit.shader");
            serialized.ApplyModifiedPropertiesWithoutUndo();
            mapObject.SetActive(true);
            // executeMethod runs outside the player loop, so Unity does not
            // guarantee that Awake has executed before the next C# line.
            // Invoke the private lifecycle hook once to validate the actual
            // allocation/upload code without entering Play mode.
            typeof(PointCloudRenderer)
                .GetMethod("Awake", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(cloud, null);
            var validFrame = new float[maxPoints * 2];
            for (var i = 0; i < validFrame.Length; i++) validFrame[i] = i * 0.001f;

            var stopwatch = Stopwatch.StartNew();
            cloud.Upload(validFrame, validFrame.Length, 2);
            stopwatch.Stop();
            if (cloud.PointCount != maxPoints)
                throw new InvalidOperationException($"Expected {maxPoints} cloud points, got {cloud.PointCount}.");

            // This represents an untrusted direct renderer caller. The public
            // API must still cap it even though the native bridge rejects it.
            var oversizedFrame = new float[maxPoints * 3];
            cloud.Upload(oversizedFrame, oversizedFrame.Length, 2);
            if (cloud.PointCount != maxPoints)
                throw new InvalidOperationException("Oversized XY cloud exceeded the renderer point cap.");

            Debug.Log($"[VizValidation] cloud frame cap: {maxPoints:N0} points, " +
                      $"upload={stopwatch.ElapsedMilliseconds} ms, " +
                      $"graphicsDevice={SystemInfo.graphicsDeviceType}.");
            UnityEngine.Object.DestroyImmediate(mapObject);
        }

        /// <summary>
        /// Locks the static virtual-wall layer to the same map-world contract
        /// as the Flutter wire payload. It is intentionally separate from
        /// cloud validation because walls only rebuild on a map switch.
        /// </summary>
        [MenuItem("Aletheia/Validate Virtual-Wall Geometry")]
        public static void ValidateVirtualWallGeometry()
        {
            var wallObject = new GameObject("FixtureVirtualWalls");
            wallObject.SetActive(false);
            wallObject.AddComponent<MeshRenderer>();
            wallObject.AddComponent<MeshFilter>();
            var walls = wallObject.AddComponent<VirtualWallRenderer>();
            var serialized = new SerializedObject(walls);
            serialized.FindProperty("wallShader").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Shader>("Assets/Shaders/VirtualWallUnlit.shader");
            serialized.ApplyModifiedPropertiesWithoutUndo();
            wallObject.SetActive(true);
            typeof(VirtualWallRenderer)
                .GetMethod("Awake", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(walls, null);

            // Two non-degenerate segments must become two independent quads.
            walls.SetWalls(new[] { new[] { -2f, 1f, 0f, 1f, 0f, 4f } });
            var mesh = wallObject.GetComponent<MeshFilter>().sharedMesh;
            if (mesh == null || mesh.vertexCount != 8 || mesh.triangles.Length != 12)
                throw new InvalidOperationException(
                    "Virtual walls did not generate one quad per map segment.");
            Debug.Log("[VizValidation] virtual walls: 2 world-stage segments, 8 vertices, 12 indices.");
            UnityEngine.Object.DestroyImmediate(wallObject);
        }
    }
}
#endif
