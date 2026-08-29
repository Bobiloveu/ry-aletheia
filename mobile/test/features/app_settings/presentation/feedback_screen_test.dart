import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/features/app_settings/presentation/feedback_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('feedback stays local in the development submission flow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AletheiaTheme.dark(),
          home: const Scaffold(body: AppFeedbackScreen()),
        ),
      ),
    );

    await tester.tap(find.text('提交反馈'));
    await tester.pump();
    expect(find.text('请填写简要说明。'), findsOneWidget);
    expect(find.text('请填写详细描述。'), findsOneWidget);

    await tester.enterText(find.byType(TextFormField).at(0), '横屏地图显示需要调整');
    await tester.enterText(
      find.byType(TextFormField).at(1),
      '切换横屏后，地图控制区覆盖了部分画面。',
    );
    await tester.tap(find.text('提交反馈'));
    await tester.pump();

    expect(find.text('反馈已完成本地校验。当前开发版本未上传或保存任何内容。'), findsOneWidget);
  });
}
