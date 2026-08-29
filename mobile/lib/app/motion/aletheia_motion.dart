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

  /// A strong, short ease-out that settles without the bounce or visual
  /// weight that would distract from a live robot workspace.
  static const easeOut = Cubic(0.23, 1, 0.32, 1);

  static Duration durationFor(BuildContext context, Duration duration) =>
      MediaQuery.disableAnimationsOf(context)
      ? const Duration(milliseconds: 100)
      : duration;

  /// Root destinations share a shell, so they cross-fade rather than slide as
  /// if the operator had navigated through a document stack.
  static Page<void> rootPage({required LocalKey key, required Widget child}) =>
      CustomTransitionPage<void>(
        key: key,
        child: child,
        transitionDuration: fast,
        reverseTransitionDuration: fast,
        transitionsBuilder: (context, animation, secondaryAnimation, child) =>
            FadeTransition(
              opacity: CurvedAnimation(parent: animation, curve: easeOut),
              child: child,
            ),
      );

  /// Secondary tools preserve a small spatial cue for drill-in and back.
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
      final opacity = FadeTransition(opacity: curved, child: child);
      if (MediaQuery.disableAnimationsOf(context)) {
        return opacity;
      }
      return SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(.015, 0),
          end: Offset.zero,
        ).animate(curved),
        child: opacity,
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
