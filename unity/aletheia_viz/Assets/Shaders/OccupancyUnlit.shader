// Map raster material used by the Unity HMI renderer.  Kept as a project
// asset—not acquired through Shader.Find—so IL2CPP includes it in iOS builds.
Shader "Aletheia/OccupancyUnlit"
{
    Properties
    {
        _BaseMap ("Occupancy Map", 2D) = "white" {}
    }
    SubShader
    {
        // The project intentionally uses Unity's built-in render pipeline.
        // Do not add a UniversalPipeline tag here: it makes this the only
        // candidate SubShader in a non-URP iOS player and Unity renders the
        // whole map as its magenta error material.
        Tags { "RenderType" = "Opaque" }
        Pass
        {
            ZWrite On
            Cull Off

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _BaseMap;

            struct Attributes
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
            };

            struct Varyings
            {
                float4 position : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                output.position = UnityObjectToClipPos(input.vertex);
                output.uv = input.uv;
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                return tex2D(_BaseMap, input.uv);
            }
            ENDCG
        }
    }
}
