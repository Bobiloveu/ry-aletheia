import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Motion tokens for the operations HMI.
///
/// The console intentionally limits motion to transitions that explain a
/// meaningful change of context or operational state. Live telemetry, map
/// panning and repeatedly used navigation remain direct and immediate.
abstract final class AletheiaMotion {
  static const fast = Duration(milliseconds: 140);
  static const standard = Duration(milliseconds: 180);

  /// Mathematical timing tokens for low-frequency, semantic interaction.
  /// They deliberately do not apply to live telemetry, map/video rendering,
  /// root navigation, or any vehicle-control transport path.
  static const pressDuration = Duration(milliseconds: 120);
  static const stateDuration = Duration(milliseconds: 180);
  static const surfaceDuration = Duration(milliseconds: 240);

  static const pressCurve = Cubic(0.23, 1, 0.32, 1);
  static const stateCurve = Cubic(0.23, 1, 0.32, 1);
  static const surfaceCurve = Cubic(0.23, 1, 0.32, 1);

  /// A strong, short ease-out that settles without the bounce or visual
  /// weight that would distract from a live robot workspace.
  static const easeOut = stateCurve;

  static bool isReducedMotion(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context);

  static Duration durationFor(BuildContext context, Duration duration) =>
      isReducedMotion(context) ? const Duration(milliseconds: 100) : duration;

  /// A theme replacement affects every HMI surface at once. Keep it direct:
  /// cross-fading the entire app can expose unrelated outgoing route content
  /// and mixes the palette while a live workspace is still visible.
  static Duration themeAnimationDuration(BuildContext context) => Duration.zero;

  /// Uses the platform bottom-sheet/dialog transition machinery while keeping
  /// both directions short and mathematically curved. The reduced-motion
  /// variant retains a short transition but removes the longer travel time.
  static AnimationStyle surfaceAnimationStyle(BuildContext context) =>
      AnimationStyle(
        duration: isReducedMotion(context)
            ? const Duration(milliseconds: 120)
            : surfaceDuration,
        reverseDuration: isReducedMotion(context)
            ? const Duration(milliseconds: 120)
            : surfaceDuration,
        curve: surfaceCurve,
        reverseCurve: surfaceCurve.flipped,
      );

  /// Root destinations are high-frequency HMI workspaces. They replace
  /// immediately instead of cross-fading: keeping the old route visible for
  /// even a short transition leaves a stale map, video, or platform-view frame
  /// on screen when the operator changes destinations rapidly.
  ///
  /// Secondary/detail pages below retain their short, contextual transition.
  static Page<void> rootPage({required LocalKey key, required Widget child}) =>
      NoTransitionPage<void>(key: key, child: child);

  /// Secondary tools preserve a small spatial cue for drill-in and back.
  ///
  /// The arriving route remains fully opaque. Fading a complete page would
  /// show the outgoing route underneath it, which is especially distracting
  /// when the previous page contains dense operational content.
  static Page<void> detailPage({
    required LocalKey key,
    required Widget child,
  }) => CustomTransitionPage<void>(
    key: key,
    child: child,
    transitionDuration: standard,
    reverseTransitionDuration: standard,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      final curved = CurvedAnimation(parent: animation, curve: easeOut);
      final canvas = Theme.of(context).scaffoldBackgroundColor;
      final opaqueSurface = ColoredBox(color: canvas, child: child);
      if (MediaQuery.disableAnimationsOf(context)) {
        return opaqueSurface;
      }
      // Keep an opaque route canvas stationary, then move only the incoming
      // content. A page body commonly starts with SafeArea/scroll content and
      // therefore does not paint its own background; translating that body
      // directly lets the prior route's labels remain visible underneath.
      return Stack(
        fit: StackFit.expand,
        children: [
          ColoredBox(color: canvas),
          SlideTransition(
            position: Tween<Offset>(
              begin: const Offset(.015, 0),
              end: Offset.zero,
            ).animate(curved),
            child: child,
          ),
        ],
      );
    },
  );
}

/// A restrained fade-through for occasional replacement of a meaningful
/// workspace or status surface. It deliberately uses no positional movement:
/// map and video data must never appear to move because their surrounding UI
/// changed state.
class AletheiaFadeThrough extends StatefulWidget {
  const AletheiaFadeThrough({
    required this.child,
    this.duration = AletheiaMotion.standard,
    super.key,
  });

  final Widget child;
  final Duration duration;

  @override
  State<AletheiaFadeThrough> createState() => _AletheiaFadeThroughState();
}

class _AletheiaFadeThroughState extends State<AletheiaFadeThrough> {
  var _canAnimate = false;

  @override
  void initState() {
    super.initState();
    // The first meaningful frame is information, not a transition. Mount it
    // fully opaque, then enable fade-through for later state replacement.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        setState(() => _canAnimate = true);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final effectiveDuration = AletheiaMotion.durationFor(
      context,
      widget.duration,
    );
    return AnimatedSwitcher(
      duration: _canAnimate ? effectiveDuration : Duration.zero,
      reverseDuration: _canAnimate ? effectiveDuration : Duration.zero,
      switchInCurve: AletheiaMotion.easeOut,
      switchOutCurve: AletheiaMotion.easeOut,
      layoutBuilder: (currentChild, previousChildren) => Stack(
        alignment: Alignment.topCenter,
        fit: StackFit.passthrough,
        children: [...previousChildren, ?currentChild],
      ),
      transitionBuilder: (child, animation) =>
          FadeTransition(opacity: animation, child: child),
      child: widget.child,
    );
  }
}
