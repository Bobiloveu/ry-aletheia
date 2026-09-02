// Opaque unlit wall pass. The HMI map runs on the built-in renderer, so this
// deliberately avoids URP-only includes and remains valid in the iOS UaaL
// export with high managed/code stripping enabled.
Shader "Aletheia/VirtualWallUnlit"
{
    Properties
    {
        _Color ("Virtual wall", Color) = (0.83, 0.24, 0.25, 1)
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry+2" }
        Pass
        {
            Cull Off
            ZWrite On
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            fixed4 _Color;
            struct Attributes { float4 vertex : POSITION; };
            struct Varyings { float4 position : SV_POSITION; };
            Varyings vert(Attributes input)
            {
                Varyings output;
                output.position = UnityObjectToClipPos(input.vertex);
                return output;
            }
            fixed4 frag(Varyings input) : SV_Target { return _Color; }
            ENDCG
        }
    }
}
