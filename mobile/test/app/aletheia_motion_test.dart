import 'package:aletheia_mobile/app/motion/aletheia_motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

void main() {
  test('root HMI destinations replace without retaining an outgoing frame', () {
    final page = AletheiaMotion.rootPage(
      key: const ValueKey('observation'),
      child: const SizedBox(),
    );

    expect(page, isA<NoTransitionPage<void>>());
  });
}
