import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// A short hand-off screen shown only for the opt-in Unity renderer build.
///
/// It makes the renderer choice explicit without turning the HMI startup into
/// a branded loading sequence. The native iOS launch screen remains generic so
/// normal Flutter and Simulator builds do not expose a Unity dependency.
class UnityStartupSplash extends StatefulWidget {
  const UnityStartupSplash({
    required this.child,
    this.enabled = true,
    super.key,
  });

  final Widget child;
  final bool enabled;

  @override
  State<UnityStartupSplash> createState() => _UnityStartupSplashState();
}

class _UnityStartupSplashState extends State<UnityStartupSplash> {
  Timer? _dismissTimer;
  var _visible = true;
  var _isPresent = true;

  @override
  void initState() {
    super.initState();
    if (widget.enabled) {
      _dismissTimer = Timer(const Duration(milliseconds: 760), () {
        if (mounted) setState(() => _visible = false);
      });
    } else {
      _visible = false;
      _isPresent = false;
    }
  }

  @override
  void didUpdateWidget(covariant UnityStartupSplash oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.enabled && !widget.enabled) {
      _dismissTimer?.cancel();
      setState(() {
        _visible = false;
        _isPresent = false;
      });
    }
  }

  @override
  void dispose() {
    _dismissTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.enabled) return widget.child;

    final theme = Theme.of(context);
    final disableAnimations = MediaQuery.disableAnimationsOf(context);
    final overlay = Semantics(
      label: 'Aletheia, powered by Unity',
      child: ColoredBox(
        color: theme.scaffoldBackgroundColor,
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  color: theme.colorScheme.surface,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: theme.colorScheme.outline),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: SvgPicture.asset(
                    'assets/branding/aletheia_icon_vector.svg',
                    width: 42,
                    height: 42,
                    semanticsLabel: 'Aletheia',
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Text('Aletheia', style: theme.textTheme.titleLarge),
              const SizedBox(height: 22),
              Container(
                width: 36,
                height: 1,
                color: theme.colorScheme.outlineVariant,
              ),
              const SizedBox(height: 14),
              Text(
                'Powered by Unity',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                  letterSpacing: 0.35,
                ),
              ),
            ],
          ),
        ),
      ),
    );

    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        if (_isPresent)
          IgnorePointer(
            child: AnimatedOpacity(
              opacity: _visible ? 1 : 0,
              duration: disableAnimations
                  ? Duration.zero
                  : const Duration(milliseconds: 180),
              curve: Curves.easeOutCubic,
              onEnd: _visible
                  ? null
                  : () {
                      if (mounted) setState(() => _isPresent = false);
                    },
              child: overlay,
            ),
          ),
      ],
    );
  }
}
