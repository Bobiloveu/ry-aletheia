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

  testWidgets('detail pages keep their surface opaque while entering', (
    tester,
  ) async {
    final page = AletheiaMotion.detailPage(
      key: const ValueKey('detail'),
      child: const SizedBox.expand(),
    ) as CustomTransitionPage<void>;

    late Widget transition;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Theme(
            data: ThemeData(scaffoldBackgroundColor: Colors.deepPurple),
            child: Builder(
              builder: (context) {
                transition = page.transitionsBuilder(
                  context,
                  kAlwaysCompleteAnimation,
                  kAlwaysDismissedAnimation,
                  page.child,
                );
                return transition;
              },
            ),
          ),
        ),
      ),
    );

    // A detail route may translate slightly for spatial context, but the
    // current page must paint an opaque canvas first. Otherwise the outgoing
    // settings/tool page shows through the incoming page's unpainted areas.
    expect(
      find.byWidgetPredicate(
        (widget) => widget is ColoredBox && widget.color == Colors.deepPurple,
      ),
      findsOneWidget,
    );
    expect(find.byType(FadeTransition), findsNothing);
    expect(find.byType(SlideTransition), findsOneWidget);
  });
}
