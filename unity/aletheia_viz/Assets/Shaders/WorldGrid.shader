// Adaptive metre grid drawn on a large ground quad. Spacing is chosen on the
// CPU (VizCamera) from the current zoom and passed in _Minor / _Major, matching
// the Flutter renderer's {0.25,0.5,1,2,5,10,20} steps.
Shader "Aletheia/WorldGrid"
{
    Properties
    {
        _Minor ("Minor spacing (m)", Float) = 1
        _Major ("Major spacing (m)", Float) = 5
        _MapOrigin ("Map canvas origin (m)", Vector) = (0,0,0,0)
        _MapSize ("Map canvas size (m)", Vector) = (1,1,0,0)
        _MinorColor ("Minor", Color) = (0.10,0.16,0.15,0.10)
        _MajorColor ("Major", Color) = (0.10,0.16,0.15,0.22)
    }
    SubShader
    {
        // This project has no URP pipeline asset assigned. Keeping this
        // shader pipeline-neutral is required for iOS instead of falling back
        // to Unity's full-screen magenta error material.
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" }
        Pass
        {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            float _Minor, _Major;
            float4 _MapOrigin, _MapSize;
            float4 _MinorColor, _MajorColor;

            struct Attributes { float4 vertex : POSITION; };
            struct Varyings { float4 pos : SV_POSITION; float2 map : TEXCOORD0; };

            Varyings vert(Attributes v)
            {
                Varyings o;
                // The Quad is authored in local XY and rotated onto XZ by
                // the scene. Reconstruct map-canvas coordinates from that
                // local geometry so a MapCanvas pan moves the raster and the
                // metre-grid as one object without changing grid phase.
                o.map = v.vertex.xy * _MapSize.xy + _MapOrigin.xy;
                o.pos = UnityObjectToClipPos(v.vertex);
                return o;
            }

            float line_mask(float2 coord, float spacing)
            {
                float2 g = abs(frac(coord / spacing - 0.5) - 0.5) / fwidth(coord / spacing);
                return 1.0 - min(min(g.x, g.y), 1.0);
            }

            half4 frag(Varyings i) : SV_Target
            {
                float2 c = i.map;
                float minor = line_mask(c, _Minor);
                float major = line_mask(c, _Major);
                half4 col = _MinorColor * minor;
                col = lerp(col, _MajorColor, major);
                col.a *= max(minor, major);
                return col;
            }
            ENDCG
        }
    }
}
