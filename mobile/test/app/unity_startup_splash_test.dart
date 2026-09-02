import 'package:aletheia_mobile/app/unity_startup_splash.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shows the Unity attribution only when enabled', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: UnityStartupSplash(
          enabled: true,
          child: Scaffold(body: Text('HMI')),
        ),
      ),
    );

    expect(find.text('Powered by Unity'), findsOneWidget);
    expect(find.text('HMI'), findsOneWidget);

    await tester.pumpWidget(
      const MaterialApp(
        home: UnityStartupSplash(
          enabled: false,
          child: Scaffold(body: Text('HMI')),
        ),
      ),
    );

    expect(find.text('Powered by Unity'), findsNothing);
    expect(find.text('HMI'), findsOneWidget);
  });

  testWidgets('hands off after the short startup interval', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: UnityStartupSplash(child: Scaffold(body: Text('HMI'))),
      ),
    );

    await tester.pump(const Duration(milliseconds: 761));
    await tester.pumpAndSettle();

    expect(find.text('Powered by Unity'), findsNothing);
    expect(find.text('HMI'), findsOneWidget);
  });
}
