using System;
using UnityEngine;

namespace Aletheia.Viz
{
    public enum VizViewMode { TwoD, ThreeD }

    /// <summary>
    /// Map placement in world metres. The occupancy raster's bottom-left
    /// corner sits at (originX, originY); +Y is north (Flutter flips Y for
    /// screen space, Unity does not). One Unity unit == one metre.
    /// </summary>
    [Serializable]
    public struct VizMap
    {
        public string id;
        public int w;      // raster width  (px)
        public int h;      // raster height (px)
        public float res;  // metres per pixel
        public float ox;   // origin x (m)
        public float oy;   // origin y (m)
        public float vlen; // vehicle length (m)
        public float vwid; // vehicle width  (m)

        public float WorldWidth => w * res;
        public float WorldHeight => h * res;
        public Vector2 WorldCenter => new(ox + WorldWidth * 0.5f, oy + WorldHeight * 0.5f);
    }

    [Serializable]
    public struct VizPose
    {
        public float x;
        public float y;
        public float yaw; // radians, map frame
        public int seq;
    }

    [Serializable]
    public struct VizCameraMsg
    {
        public float scale;
        public float ox;
        public float oy;
        public float yaw;
        public float pitch;
        public float distance;
        public float tx;
        public float ty;
        public float viewportWidth;
        public float viewportHeight;
        public float pixelsPerMetre;
        public float centerX;
        public float centerY;
        public long viewportRevision;
    }

    [Serializable]
    public struct VizLayerMsg
    {
        public string layer;
        public bool v;
    }

    /// <summary>Ownership token for the process-wide Unity renderer.</summary>
    [Serializable]
    public struct SessionEnvelope
    {
        public long owner;
    }
}
