import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(AletheiaTheme.dark);

  test('daylight uses a light, low-glare palette with semantic contrast', () {
    final theme = AletheiaTheme.light();

    expect(theme.brightness, Brightness.light);
    expect(theme.scaffoldBackgroundColor, const Color(0xFFF5F8FC));
    expect(theme.cardTheme.color, const Color(0xFFFFFFFF));
    expect(theme.colorScheme.primary, const Color(0xFF0A63C4));
    expect(theme.colorScheme.onPrimary, const Color(0xFFFFFFFF));
    expect(AletheiaTheme.mapVirtualWall, const Color(0xFFB6433D));
    expect(
      theme.appBarTheme.systemOverlayStyle?.statusBarBrightness,
      Brightness.light,
    );
  });

  test('daylight major map grid remains discernible over white free space', () {
    AletheiaTheme.light();

    final compositedLine = Color.alphaBlend(
      AletheiaTheme.mapGridMajor,
      Colors.white,
    );

    expect(
      _contrastRatio(compositedLine, Colors.white),
      greaterThanOrEqualTo(1.2),
    );
  });

  test('the default HMI treatment remains dark', () {
    final theme = AletheiaTheme.dark();

    expect(theme.brightness, Brightness.dark);
    expect(theme.scaffoldBackgroundColor, const Color(0xFF101415));
    expect(
      theme.appBarTheme.systemOverlayStyle?.statusBarBrightness,
      Brightness.dark,
    );
  });
}

double _contrastRatio(Color first, Color second) {
  final lighter = first.computeLuminance() > second.computeLuminance()
      ? first.computeLuminance()
      : second.computeLuminance();
  final darker = first.computeLuminance() > second.computeLuminance()
      ? second.computeLuminance()
      : first.computeLuminance();
  return (lighter + .05) / (darker + .05);
}
