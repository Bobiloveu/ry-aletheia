import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(AletheiaTheme.dark);

  test('daylight uses a light, low-glare palette with semantic contrast', () {
    final theme = AletheiaTheme.light();

    expect(theme.brightness, Brightness.light);
    expect(theme.scaffoldBackgroundColor, const Color(0xFFF2F6F5));
    expect(theme.cardTheme.color, const Color(0xFFFCFEFD));
    expect(theme.colorScheme.primary, const Color(0xFF216D65));
    expect(theme.colorScheme.onPrimary, const Color(0xFFF8FCFB));
    expect(AletheiaTheme.mapVirtualWall, const Color(0xFFB6433D));
  });

  test('the default HMI treatment remains dark', () {
    final theme = AletheiaTheme.dark();

    expect(theme.brightness, Brightness.dark);
    expect(theme.scaffoldBackgroundColor, const Color(0xFF101415));
  });
}
