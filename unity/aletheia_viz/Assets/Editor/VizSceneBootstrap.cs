#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Aletheia.Viz.EditorTools
{
    /// <summary>
    /// Builds <c>Assets/Scenes/Viz.unity</c> from scratch so the scene graph is
    /// reviewable in version control as code rather than a binary .unity file.
    /// Run once via the menu after opening the project; commit the result.
    /// </summary>
    public static class VizSceneBootstrap
    {
        [MenuItem("Aletheia/Rebuild Viz Scene")]
        public static void Rebuild()
        {
            var scene = EditorSceneManager.NewScene(
                NewSceneSetup.EmptyScene, NewSceneMode.Single);

            // Root
            var root = new GameObject("VizRoot");
            var bridge = root.AddComponent<VizBridge>();

            // One world-stage for all map-space layers.  Runtime also creates
            // this canvas for existing scenes, but serializing it here keeps
            // future exports inspectable and matches the mobile web design.
            var mapCanvas = new GameObject("MapCanvas");
            mapCanvas.transform.SetParent(root.transform, false);

            // Camera
            var camGo = new GameObject("VizCamera");
            camGo.transform.SetParent(root.transform);
            var camera = camGo.AddComponent<Camera>();
            camera.orthographic = true;
            var vizCam = camGo.AddComponent<VizCamera>();

            // Grid quad
            var gridGo = GameObject.CreatePrimitive(PrimitiveType.Quad);
            gridGo.name = "WorldGrid";
            gridGo.transform.SetParent(mapCanvas.transform);
            gridGo.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            gridGo.transform.localScale = Vector3.one * 4000f;
            Object.DestroyImmediate(gridGo.GetComponent<Collider>());
            var gridMat = new Material(Shader.Find("Aletheia/WorldGrid"));
            SaveAsset(gridMat, "Assets/Materials/WorldGrid.mat");
            // Explicitly update existing material assets as well: `SaveAsset`
            // intentionally preserves their identity, so shader defaults alone
            // would leave old device exports with the previous white-on-dark
            // grid after the canvas changed to light.
            gridMat = AssetDatabase.LoadAssetAtPath<Material>(
                "Assets/Materials/WorldGrid.mat");
            gridMat.SetColor("_MinorColor", new Color(0.10f, 0.16f, 0.15f, 0.10f));
            gridMat.SetColor("_MajorColor", new Color(0.10f, 0.16f, 0.15f, 0.22f));
            EditorUtility.SetDirty(gridMat);
            gridGo.GetComponent<MeshRenderer>().sharedMaterial = gridMat;

            // Occupancy quad
            var occGo = GameObject.CreatePrimitive(PrimitiveType.Quad);
            occGo.name = "OccupancyMap";
            occGo.transform.SetParent(mapCanvas.transform);
            occGo.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            Object.DestroyImmediate(occGo.GetComponent<Collider>());
            var occ = occGo.AddComponent<OccupancyMap>();
            // Keep the map material serialized in the scene. The runtime
            // clones it before assigning the live raster, which makes the
            // built-in occupancy shader a deliberate player dependency.
            var occSo = new SerializedObject(occ);
            occSo.FindProperty("occupancyMaterial").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Material>(
                    "Assets/Materials/OccupancyMap.mat");
            occSo.ApplyModifiedPropertiesWithoutUndo();

            // Point cloud
            var cloudGo = new GameObject("PointCloud",
                typeof(MeshRenderer), typeof(MeshFilter));
            cloudGo.transform.SetParent(mapCanvas.transform);
            var cloud = cloudGo.AddComponent<PointCloudRenderer>();
            // Keep a serialized shader reference in the scene.  The iOS
            // player strips shaders only reached by Shader.Find, while this
            // direct asset dependency guarantees the procedural point pass is
            // included in UnityFramework.
            var cloudSo = new SerializedObject(cloud);
            cloudSo.FindProperty("pointShader").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Shader>(
                    "Assets/Shaders/PointCloudUnlit.shader");
            cloudSo.ApplyModifiedPropertiesWithoutUndo();

            // Virtual walls are a static map layer in the same MapCanvas as
            // occupancy, cloud and robot. A direct shader reference prevents
            // iOS high stripping from removing this small unlit pass.
            var wallsGo = new GameObject("VirtualWalls",
                typeof(MeshRenderer), typeof(MeshFilter));
            wallsGo.transform.SetParent(mapCanvas.transform);
            var walls = wallsGo.AddComponent<VirtualWallRenderer>();
            var wallsSo = new SerializedObject(walls);
            wallsSo.FindProperty("wallShader").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<Shader>(
                    "Assets/Shaders/VirtualWallUnlit.shader");
            wallsSo.ApplyModifiedPropertiesWithoutUndo();

            // Robot
            var robotGo = new GameObject("Robot");
            robotGo.transform.SetParent(mapCanvas.transform);
            var footprint = GameObject.CreatePrimitive(PrimitiveType.Quad);
            footprint.name = "Footprint";
            footprint.transform.SetParent(robotGo.transform);
            footprint.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            Object.DestroyImmediate(footprint.GetComponent<Collider>());
            var body = GameObject.CreatePrimitive(PrimitiveType.Cube);
            body.name = "Body3D";
            body.transform.SetParent(robotGo.transform);
            Object.DestroyImmediate(body.GetComponent<Collider>());
            body.SetActive(false);
            var robot = robotGo.AddComponent<RobotMarker>();
            // Keep every 2D vehicle material serialized in the scene. iOS
            // player stripping cannot then remove the marker shader merely
            // because the runtime creates the small layered meshes itself.
            var hullMat = CreateRobotMaterial(
                "Assets/Materials/VehicleHull.mat", new Color(0.075f, 0.11f, 0.12f));
            var deckMat = CreateRobotMaterial(
                "Assets/Materials/VehicleDeck.mat", new Color(0.886f, 0.706f, 0.431f));
            var headingMat = CreateRobotMaterial(
                "Assets/Materials/VehicleHeading.mat", new Color(0.09f, 0.18f, 0.19f));

            // Wire serialized refs
            var so = new SerializedObject(bridge);
            so.FindProperty("cam").objectReferenceValue = vizCam;
            so.FindProperty("occupancy").objectReferenceValue = occ;
            so.FindProperty("cloud").objectReferenceValue = cloud;
            so.FindProperty("robot").objectReferenceValue = robot;
            so.FindProperty("virtualWalls").objectReferenceValue = walls;
            so.FindProperty("grid").objectReferenceValue = gridGo.GetComponent<MeshRenderer>();
            so.FindProperty("mapCanvas").objectReferenceValue = mapCanvas.transform;
            so.ApplyModifiedPropertiesWithoutUndo();

            var camSo = new SerializedObject(vizCam);
            camSo.FindProperty("gridMaterial").objectReferenceValue = gridMat;
            camSo.ApplyModifiedPropertiesWithoutUndo();

            var robotSo = new SerializedObject(robot);
            robotSo.FindProperty("footprint").objectReferenceValue = footprint.transform;
            robotSo.FindProperty("body3D").objectReferenceValue = body.transform;
            robotSo.FindProperty("hullMaterial").objectReferenceValue = hullMat;
            robotSo.FindProperty("deckMaterial").objectReferenceValue = deckMat;
            robotSo.FindProperty("headingMaterial").objectReferenceValue = headingMat;
            robotSo.ApplyModifiedPropertiesWithoutUndo();

            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, "Assets/Scenes/Viz.unity");
            var list = new EditorBuildSettingsScene[]
            {
                new("Assets/Scenes/Viz.unity", true),
            };
            EditorBuildSettings.scenes = list;
            Debug.Log("[Viz] scene rebuilt.");
        }

        private static void SaveAsset(Object obj, string path)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            if (!File.Exists(path)) AssetDatabase.CreateAsset(obj, path);
        }

        private static Material CreateRobotMaterial(string path, Color color)
        {
            var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (existing == null)
            {
                existing = new Material(Shader.Find("Aletheia/RobotMarkerUnlit"));
                SaveAsset(existing, path);
                existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            }
            existing.SetColor("_Color", color);
            EditorUtility.SetDirty(existing);
            return existing;
        }
    }
}
#endif
