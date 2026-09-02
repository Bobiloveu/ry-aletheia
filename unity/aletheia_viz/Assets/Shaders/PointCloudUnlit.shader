// Unlit screen-space quads fed from a StructuredBuffer. One draw call for the
// whole cloud.  Metal does not reliably preserve PSIZE from procedural point
// primitives in a Unity-as-a-Library build, so every sample is expanded into a
// six-vertex quad in the vertex stage.  This keeps the frontend-calibrated
// screen-pixel diameter without a geometry shader or per-point GameObjects.
Shader "Aletheia/PointCloudUnlit"
{
    Properties
    {
        _Color ("Color", Color) = (0.106, 0.639, 0.722, 1)
        _PointSize ("Point Size (m)", Float) = 0.082
    }
    SubShader
    {
        // See WorldGrid.shader: the iOS player uses the built-in renderer, so
        // a UniversalPipeline-only pass is intentionally not valid here.
        Tags { "RenderType" = "Opaque" }
        Pass
        {
            ZWrite On
            Cull Off

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 4.5

            #include "UnityCG.cginc"

            StructuredBuffer<float> _Points;
            int _Stride;
            float4 _Color;
            float _PointSize;
            float3 _CanvasOffset;

            struct v2f
            {
                float4 pos : SV_POSITION;
            };

            float2 QuadCorner(uint vertexInQuad)
            {
                // Two clockwise triangles, expressed as unit-square corners.
                if (vertexInQuad == 0) return float2(-1.0, -1.0);
                if (vertexInQuad == 1) return float2( 1.0, -1.0);
                if (vertexInQuad == 2) return float2( 1.0,  1.0);
                if (vertexInQuad == 3) return float2(-1.0, -1.0);
                if (vertexInQuad == 4) return float2( 1.0,  1.0);
                return float2(-1.0, 1.0);
            }

            v2f vert(uint id : SV_VertexID)
            {
                uint pointId = id / 6u;
                float3 world = float3(
                    _Points[pointId * _Stride + 0],
                    _Points[pointId * _Stride + 1],
                    _Points[pointId * _Stride + 2]) + _CanvasOffset;

                v2f o;
                o.pos = mul(UNITY_MATRIX_VP, float4(world, 1.0));
                // Convert the calibrated map-world diameter to screen pixels.
                // In orthographic map mode clip-space w is always 1, so the
                // former `_PointSize * screenHeight / w` formula inflated a
                // 0.05 m map sample into a 20–30 px blob. Match the frontend
                // mobile renderer's 0.82 source-map-pixel radius instead.
                float pixelsPerMetre;
                if (unity_OrthoParams.w > 0.5)
                {
                    pixelsPerMetre = _ScreenParams.y /
                        max(2.0 * unity_OrthoParams.y, 0.001);
                }
                else
                {
                    float focalLength = abs(UNITY_MATRIX_P._m11);
                    pixelsPerMetre = 0.5 * _ScreenParams.y * focalLength /
                        max(o.pos.w, 0.001);
                }
                // The upper bound only protects extreme 3D close-ups. In 2D
                // the size remains proportional to zoom, just like PixiJS.
                float diameterPixels = clamp(_PointSize * pixelsPerMetre, 1.0, 12.0);
                // Clip-space x/y span [-w, +w], hence two clip units per
                // screen dimension.  Multiplying by w keeps quads correct in
                // perspective mode as well as the orthographic map camera.
                float2 halfSizeClip = diameterPixels * o.pos.w / _ScreenParams.xy;
                o.pos.xy += QuadCorner(id % 6u) * halfSizeClip;
                return o;
            }

            half4 frag(v2f i) : SV_Target
            {
                return half4(_Color.rgb, 1);
            }
            ENDCG
        }
    }
}
