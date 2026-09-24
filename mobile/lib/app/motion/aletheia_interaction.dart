import 'package:flutter/material.dart';

import 'aletheia_motion.dart';

/// A presentation-only press response for a descendant that already owns its
/// own tap recognizer (typically [InkWell]). Pointer events are observed, not
/// claimed, so wrapping a robot operation never changes its hit testing or
/// callback timing.
class AletheiaPressFeedback extends StatefulWidget {
  const AletheiaPressFeedback({
    required this.child,
    this.enabled = true,
    super.key,
  });

  final Widget child;
  final bool enabled;

  @override
  State<AletheiaPressFeedback> createState() => _AletheiaPressFeedbackState();
}

class _AletheiaPressFeedbackState extends State<AletheiaPressFeedback>
    with SingleTickerProviderStateMixin {
  final _surfaceKey = GlobalKey();
  late final AnimationController _controller;
  late final Animation<double> _scale;
  int? _pressedPointer;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: AletheiaMotion.pressDuration,
      reverseDuration: AletheiaMotion.pressDuration,
    );
    _scale = Tween<double>(begin: 1, end: .97).animate(
      CurvedAnimation(parent: _controller, curve: AletheiaMotion.pressCurve),
    );
  }

  @override
  void didUpdateWidget(covariant AletheiaPressFeedback oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled && oldWidget.enabled) _controller.value = 0;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _setPressed(bool pressed) {
    if (!widget.enabled || AletheiaMotion.isReducedMotion(context)) return;
    // Surface feedback must be visible in the input frame, not after the
    // first animation tick. The remaining mathematical curve settles the
    // press toward its physical target without delaying descendant gestures.
    if (pressed && _controller.value == 0) _controller.value = .35;
    _controller.animateTo(
      pressed ? 1 : 0,
      duration: AletheiaMotion.pressDuration,
      curve: AletheiaMotion.pressCurve,
    );
  }

  void _handlePointerDown(PointerDownEvent event) {
    _pressedPointer = event.pointer;
    _setPressed(true);
  }

  void _handlePointerMove(PointerMoveEvent event) {
    if (event.pointer != _pressedPointer) return;
    final renderObject = _surfaceKey.currentContext?.findRenderObject();
    if (renderObject is! RenderBox) return;
    _setPressed(renderObject.paintBounds.contains(event.localPosition));
  }

  void _handlePointerEnd(PointerEvent event) {
    if (event.pointer != _pressedPointer) return;
    _pressedPointer = null;
    _setPressed(false);
  }

  @override
  Widget build(BuildContext context) => Listener(
    key: _surfaceKey,
    // Observe a full visual card even when a decorative child itself does not
    // paint a hit-test target. Listener remains passive in the gesture arena.
    behavior: HitTestBehavior.opaque,
    onPointerDown: _handlePointerDown,
    onPointerMove: _handlePointerMove,
    onPointerUp: _handlePointerEnd,
    onPointerCancel: _handlePointerEnd,
    child: AnimatedBuilder(
      animation: _controller,
      child: widget.child,
      builder: (context, child) => Transform.scale(
        key: const ValueKey('aletheia-press-transform'),
        scale: AletheiaMotion.isReducedMotion(context) ? 1 : _scale.value,
        child: child,
      ),
    ),
  );
}

/// A tiny keyed replacement for labels and badges whose state would otherwise
/// teleport. It is intentionally unsuitable for maps, video and telemetry.
class AletheiaStatusTransition extends StatelessWidget {
  const AletheiaStatusTransition({
    required this.stateKey,
    required this.child,
    super.key,
  });

  final Object stateKey;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final reducedMotion = AletheiaMotion.isReducedMotion(context);
    final duration = AletheiaMotion.durationFor(
      context,
      AletheiaMotion.stateDuration,
    );
    return AnimatedSwitcher(
      duration: duration,
      reverseDuration: duration,
      switchInCurve: AletheiaMotion.stateCurve,
      switchOutCurve: AletheiaMotion.stateCurve.flipped,
      // Status updates communicate the latest operational fact. Keeping the
      // previous label in the tree during the fade creates a duplicated,
      // ambiguous status frame when connectivity or control state changes.
      layoutBuilder: (currentChild, previousChildren) =>
          currentChild ?? const SizedBox.shrink(),
      transitionBuilder: (child, animation) {
        final opacity = FadeTransition(opacity: animation, child: child);
        if (reducedMotion) return opacity;
        return ScaleTransition(
          scale: Tween<double>(begin: .985, end: 1).animate(animation),
          child: opacity,
        );
      },
      child: KeyedSubtree(key: ValueKey<Object>(stateKey), child: child),
    );
  }
}

/// De-duplicates semantic haptic events emitted from a page-owned UI state.
/// It does not call platform services itself, keeping business state and
/// testing independent from a device haptic engine.
class AletheiaHapticGate {
  final Set<String> _emitted = <String>{};

  Future<void> triggerOnce(String eventId, Future<void> Function() emit) async {
    if (!_emitted.add(eventId)) return;
    await emit();
  }

  void reset() => _emitted.clear();
}
