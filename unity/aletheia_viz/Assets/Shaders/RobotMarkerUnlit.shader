Shader "Aletheia/RobotMarkerUnlit"
{
    Properties { _Color ("Color", Color) = (1,1,1,1) }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" }
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
            struct Varyings { float4 pos : SV_POSITION; };
            Varyings vert(Attributes input)
            {
                Varyings output;
                output.pos = UnityObjectToClipPos(input.vertex);
                return output;
            }
            fixed4 frag(Varyings input) : SV_Target { return _Color; }
            ENDCG
        }
    }
}
