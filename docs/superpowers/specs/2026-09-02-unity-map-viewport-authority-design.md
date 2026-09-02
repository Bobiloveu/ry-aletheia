# Unity Map Viewport Authority Design

## Goal

Make the Unity map preserve map-space geometry through portrait, landscape,
fullscreen entry, and fullscreen return on Android and iOS.  A map metre must
always occupy the same number of displayed pixels in both axes for a given
Flutter HMI camera state.

## Evidence and root cause

The working frontend keeps one viewport model: a `ResizeObserver` updates the
map viewport, resets `pixelsPerMeter`, and the Pixi world stage then uses that
same value for every map layer.  The current Unity path differs in two ways:

1. Flutter derives `scale` and offsets from `LayoutBuilder`, but emits them
   independently from the native platform view's resize lifecycle.
2. `VizCamera.OnPreCull` derives `Camera.aspect` from Unity's internal render
   buffer.  During UaaL host reparenting that buffer can temporarily retain the
   previous card/fullscreen orientation while Flutter is already composing it
   into the new logical viewport.

Those two transforms can disagree for one or more rendered frames.  The
Android screenshots show the resulting anisotropic map: the same occupancy
raster has different displayed aspect ratios in portrait and landscape.

## Architecture

Flutter is the only authority for the logical map viewport.  It will publish a
complete camera packet whenever either interaction state or `LayoutBuilder`
dimensions change:

```text
width, height, pixelsPerMetre, centreX, centreY, revision
```

`pixelsPerMetre` is derived from the existing Flutter gesture camera and map
metadata.  `centreX` and `centreY` are map-world metres.  Width and height are
Flutter logical pixels; their ratio, rather than Unity's transient internal
buffer ratio, is the projection contract.

Unity consumes the packet atomically.  In 2D it sets:

```text
Camera.aspect           = width / height
Camera.orthographicSize = height / (2 * pixelsPerMetre)
MapCanvas.position      = (-centreX, 0, -centreY)
```

Consequently the visible horizontal span is `width / pixelsPerMetre` and the
visible vertical span is `height / pixelsPerMetre`.  If Android temporarily
composites a stale internal buffer into a new host size, Unity intentionally
uses the Flutter logical aspect so the final composition remains isotropic.

The Android host retains its layout-managed `SurfaceHolder` resizing only as a
native-surface availability mechanism.  It will no longer be responsible for
choosing map projection values.

## Scope and boundaries

- Unity remains display-only; no robot protocol, network, video, or business
  logic changes.
- The existing Flutter CustomPaint renderer remains unchanged.
- Map raster, grid, walls, cloud, and vehicle remain children of `MapCanvas`.
- Fullscreen routes continue to use one process-wide Unity runtime.
- The old `OnPreCull` `pixelWidth/pixelHeight` projection calculation is
  removed so no second projection authority remains.

## Verification

1. A pure Dart viewport model test verifies portrait and landscape packets
   generate expected metres-per-pixel from the same `VizCameraState`.
2. A Unity editor validation verifies the projection equations produce equal
   X/Y displayed scale for portrait, landscape, and the card/fullscreen sizes
   observed on the physical Android device.
3. A source/ABI contract test verifies width and height travel through Dart
   FFI, the C header, and Unity's `AvCamera` struct.
4. Android Debug Gallery performs five fullscreen enter/exit cycles with the
   deterministic map fixture.  Logs record Flutter logical viewport, Unity
   received viewport, render buffer, and resulting orthographic projection;
   every frame must report the same displayed X/Y metre scale.
5. Run `flutter analyze`, targeted and full Flutter tests, the Unity batch
   validation, Android build, and then manual Android portrait/landscape plus
   fullscreen-return checks before packaging.
