# Aletheia Mobile Design System

## Intent

Aletheia Mobile is a Mobile Robot HMI / Test & Diagnostic Console for trusted
local-network robots. It brings robot status, real-time visualisation, testing,
and diagnostics into one mobile HMI surface.

The default visual language is a restrained graphite information surface:
compact, legible, and calm under operational pressure. A separately reviewed
daylight palette uses a cool, low-glare field background for bright work areas.
It is not a marketing interface and does not use decorative gradients, glass
layers, or autonomous motion. Observation remains visually and architecturally
separate from any future Operation / Command capability.

## Tokens

| Role | Token | Value |
| --- | --- | --- |
| App background | `canvas` | `#101415` |
| Standard surface | `surface` | `#181E20` |
| Raised control surface | `surfaceRaised` | `#20282A` |
| Recessed navigation and quiet blocks | `surfaceSunken` / `surfaceMuted` | `#0C1011` / `#141A1C` |
| Primary text | `textPrimary` | `#EAF0EF` |
| Secondary text | `textSecondary` | `#B5C1BF` |
| Supporting text | `textTertiary` | `#82918F` |
| Standard border | `border` | `#354140` |
| Primary action and neutral signal | `cyan` | `#9BC7C0` |
| Success | `mint` | `#8CC49A` |
| Warning | `warning` | `#E2B46E` |
| Error | `danger` | `#DD837B` |

## Daylight palette

Daylight is an explicit handset preference, not automatic colour inversion.
It keeps the same hierarchy, radius, type, controls and semantic meanings as
the default HMI dark treatment.

| Role | Token | Value |
| --- | --- | --- |
| App background | `canvas` | `#F2F6F5` |
| Standard surface | `surface` | `#FCFEFD` |
| Raised control surface | `surfaceRaised` | `#E8EFED` |
| Recessed navigation and quiet blocks | `surfaceSunken` / `surfaceMuted` | `#E6EEEC` / `#EDF3F1` |
| Primary text | `textPrimary` | `#16201F` |
| Secondary text | `textSecondary` | `#41504E` |
| Supporting text | `textTertiary` | `#667573` |
| Standard border | `border` | `#C5D1CE` |
| Primary action and neutral signal | `cyan` | `#216D65` |
| Success / warning / error | `mint` / `warning` / `danger` | `#287243` / `#8C5B08` / `#B5423B` |

Pure white and pure black are intentionally avoided. The daylight primary
action uses an off-white foreground with sufficient contrast; status colours
remain reserved for real state, never decoration. Map, PointCloud, robot and
virtual-wall layers keep distinct semantic colours in both palettes.

Semantic colours communicate a real action or status. They are not decoration.
The primary signal is used for the selected destination, primary action, focus,
and neutral in-progress state. Success, warning, and error retain their status
meaning across all screens.

## Type and spacing

- Use the platform system typeface through Material 3. `headlineSmall` is 25px
  at 700 weight; section titles are 16px at 700; body copy is 14px with 1.45
  line height; supporting text is 12px.
- Keep page titles left aligned. Small icon labels can identify a page or a
  panel, but must not use all-caps tracking as decoration.
- Use a 4px rhythm. Common gaps are 8, 12, 16, 20, 24, and 32px.
- Controls use a 10px radius, grouped status surfaces use 14px, and primary
  panels use 18px. Pills are reserved for concise status and metadata.

## Surfaces and interaction

- Panels use one-pixel `border` outlines and no decorative drop shadows.
- Inputs use `surfaceRaised`; their focus ring is the primary signal colour.
- Standard navigation uses `surfaceSunken`, separated structurally from page content. The short-landscape instrument strip is the exception: it shares the `canvas` background with the active HMI workspace, so its boundary is a quiet structural divider rather than a heavy dark slab.
- Short landscape uses a 56pt icon-only instrument navigation strip with 44pt destinations and a 44pt header. Robot, Observation and Tools are the three HMI workspaces; Settings is a separate phone-local primary destination and never becomes a robot tool. The selected destination uses the neutral raised-control surface and signal-colour icon. The strip does not add a permanent blank safe-area column: the divider stays tight to the left when the Dynamic Island is on the trailing side, and only reserves the leading system inset when necessary to keep controls reachable. Labels remain available through Tooltip and accessibility semantics.
- Buttons must stay at least 46px high. The primary action uses the signal
  colour; cancellation remains outlined and uses the error colour only when it
  is truly destructive.
- Material press feedback is retained. There are no automatic or looping
  animations in this high-frequency operational flow.
- Switching appearance is an explicit user preference. The HMI keeps its
  content and geometry stable while only the palette changes, so map evidence
  never appears to move or reflow because of a visual preference.
- A map may contain only lightweight map-specific controls. Persistent pose
  and point-cloud readouts sit directly below it or in a dedicated side area,
  never as opaque cards over map evidence.
