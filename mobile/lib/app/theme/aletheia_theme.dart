import 'package:flutter/material.dart';

/// Shared visual language for the mobile operations console.
///
/// The existing feature surfaces use these semantic tokens directly. The
/// active palette is selected while the root [ThemeData] is built, so every
/// workspace, including the map and video chrome, changes as one coherent
/// theme rather than leaving dark-only cards on a daylight canvas.
abstract final class AletheiaTheme {
  static const _hmiDark = _AletheiaPalette(
    canvas: Color(0xFF101415),
    surface: Color(0xFF181E20),
    surfaceRaised: Color(0xFF20282A),
    surfaceSunken: Color(0xFF0C1011),
    surfaceMuted: Color(0xFF141A1C),
    textPrimary: Color(0xFFEAF0EF),
    textSecondary: Color(0xFFB5C1BF),
    textTertiary: Color(0xFF82918F),
    border: Color(0xFF354140),
    divider: Color(0xFF283230),
    cyan: Color(0xFF9BC7C0),
    mint: Color(0xFF8CC49A),
    warning: Color(0xFFE2B46E),
    danger: Color(0xFFDD837B),
    mapPointCloud: Color(0xFF1BA3B8),
    mapVirtualWall: Color(0xFFE06F67),
    mapRobot: Color(0xFFE2B46E),
    mapRobotOutline: Color(0xFF17201F),
    onPrimary: Color(0xFF10201E),
    onSecondary: Color(0xFF102117),
    primaryContainer: Color(0xFF20332F),
    secondaryContainer: Color(0xFF213027),
    errorContainer: Color(0xFF3A211E),
    onError: Color(0xFF32110F),
  );

  static const _highContrastDark = _AletheiaPalette(
    canvas: Color(0xFF0B0E0F),
    surface: Color(0xFF12191A),
    surfaceRaised: Color(0xFF1B2526),
    surfaceSunken: Color(0xFF070A0B),
    surfaceMuted: Color(0xFF101718),
    textPrimary: Color(0xFFF5FBF9),
    textSecondary: Color(0xFFD2DEDB),
    textTertiary: Color(0xFFA7B6B2),
    border: Color(0xFF62706D),
    divider: Color(0xFF3F4C4A),
    cyan: Color(0xFFC5ECE4),
    mint: Color(0xFF9BD4A8),
    warning: Color(0xFFF0C87F),
    danger: Color(0xFFF09B92),
    mapPointCloud: Color(0xFF39B7CA),
    mapVirtualWall: Color(0xFFF1877D),
    mapRobot: Color(0xFFF0C87F),
    mapRobotOutline: Color(0xFF0C1313),
    onPrimary: Color(0xFF0C1A18),
    onSecondary: Color(0xFF0E2114),
    primaryContainer: Color(0xFF29423D),
    secondaryContainer: Color(0xFF2A4230),
    errorContainer: Color(0xFF482622),
    onError: Color(0xFF2F110F),
  );

  /// Daylight is a cool, low-glare field palette. It avoids pure white and
  /// preserves a clear separation between canvas, working surfaces and input
  /// controls in bright operational environments.
  static const _daylight = _AletheiaPalette(
    canvas: Color(0xFFF2F6F5),
    surface: Color(0xFFFCFEFD),
    surfaceRaised: Color(0xFFE8EFED),
    surfaceSunken: Color(0xFFE6EEEC),
    surfaceMuted: Color(0xFFEDF3F1),
    textPrimary: Color(0xFF16201F),
    textSecondary: Color(0xFF41504E),
    textTertiary: Color(0xFF667573),
    border: Color(0xFFC5D1CE),
    divider: Color(0xFFD9E3E0),
    cyan: Color(0xFF216D65),
    mint: Color(0xFF287243),
    warning: Color(0xFF8C5B08),
    danger: Color(0xFFB5423B),
    mapPointCloud: Color(0xFF087D93),
    mapVirtualWall: Color(0xFFB6433D),
    mapRobot: Color(0xFF9B650B),
    mapRobotOutline: Color(0xFF16201F),
    onPrimary: Color(0xFFF8FCFB),
    onSecondary: Color(0xFFF8FCF9),
    primaryContainer: Color(0xFFD3E8E3),
    secondaryContainer: Color(0xFFD8EBD9),
    errorContainer: Color(0xFFF5DDDA),
    onError: Color(0xFFFFF8F7),
  );

  static _AletheiaPalette _activePalette = _hmiDark;

  static Color get canvas => _activePalette.canvas;
  static Color get surface => _activePalette.surface;
  static Color get surfaceRaised => _activePalette.surfaceRaised;
  static Color get surfaceSunken => _activePalette.surfaceSunken;
  static Color get surfaceMuted => _activePalette.surfaceMuted;
  static Color get textPrimary => _activePalette.textPrimary;
  static Color get textSecondary => _activePalette.textSecondary;
  static Color get textTertiary => _activePalette.textTertiary;
  static Color get border => _activePalette.border;
  static Color get divider => _activePalette.divider;
  static Color get cyan => _activePalette.cyan;
  static Color get mint => _activePalette.mint;
  static Color get warning => _activePalette.warning;
  static Color get danger => _activePalette.danger;
  static Color get mapPointCloud => _activePalette.mapPointCloud;
  static Color get mapVirtualWall => _activePalette.mapVirtualWall;
  static Color get mapRobot => _activePalette.mapRobot;
  static Color get mapRobotOutline => _activePalette.mapRobotOutline;

  static const double controlRadius = 10;
  static const double sectionRadius = 14;
  static const double panelRadius = 18;

  static ThemeData dark({bool highContrast = false}) => _build(
    highContrast ? _highContrastDark : _hmiDark,
    brightness: Brightness.dark,
  );

  static ThemeData light() => _build(_daylight, brightness: Brightness.light);

  static ThemeData _build(
    _AletheiaPalette palette, {
    required Brightness brightness,
  }) {
    _activePalette = palette;
    final text = textPrimary;
    final secondaryText = textSecondary;
    final outline = border;
    final colors = ColorScheme(
      brightness: brightness,
      primary: cyan,
      onPrimary: palette.onPrimary,
      primaryContainer: palette.primaryContainer,
      onPrimaryContainer: cyan,
      secondary: mint,
      onSecondary: palette.onSecondary,
      secondaryContainer: palette.secondaryContainer,
      onSecondaryContainer: mint,
      error: danger,
      onError: palette.onError,
      errorContainer: palette.errorContainer,
      onErrorContainer: danger,
      surface: surface,
      onSurface: text,
      outline: outline,
    );

    final textTheme = TextTheme(
      headlineSmall: TextStyle(
        color: text,
        fontSize: 25,
        fontWeight: FontWeight.w700,
        height: 1.16,
        letterSpacing: -0.45,
      ),
      titleLarge: TextStyle(
        color: text,
        fontSize: 20,
        fontWeight: FontWeight.w700,
        height: 1.2,
        letterSpacing: -0.2,
      ),
      titleMedium: TextStyle(
        color: text,
        fontSize: 16,
        fontWeight: FontWeight.w700,
        height: 1.25,
      ),
      bodyLarge: TextStyle(color: text, fontSize: 16, height: 1.45),
      bodyMedium: TextStyle(color: secondaryText, fontSize: 14, height: 1.45),
      bodySmall: TextStyle(color: textTertiary, fontSize: 12, height: 1.4),
      labelLarge: TextStyle(
        color: text,
        fontSize: 14,
        fontWeight: FontWeight.w700,
        height: 1.15,
        letterSpacing: 0.1,
      ),
      labelMedium: TextStyle(
        color: secondaryText,
        fontSize: 12,
        fontWeight: FontWeight.w600,
        height: 1.2,
        letterSpacing: 0.15,
      ),
    );

    final inputShape = OutlineInputBorder(
      borderRadius: BorderRadius.circular(controlRadius),
      borderSide: BorderSide(color: outline),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colors,
      scaffoldBackgroundColor: canvas,
      textTheme: textTheme,
      visualDensity: VisualDensity.standard,
      appBarTheme: AppBarTheme(
        backgroundColor: canvas,
        foregroundColor: text,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        toolbarHeight: 64,
        titleTextStyle: TextStyle(
          color: text,
          fontSize: 17,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.15,
        ),
      ),
      cardTheme: CardThemeData(
        color: surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(sectionRadius),
          side: BorderSide(color: outline),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surfaceRaised,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 15,
        ),
        labelStyle: TextStyle(color: secondaryText),
        hintStyle: TextStyle(color: textTertiary),
        helperStyle: TextStyle(color: textTertiary),
        prefixIconColor: secondaryText,
        border: inputShape,
        enabledBorder: inputShape,
        focusedBorder: inputShape.copyWith(
          borderSide: BorderSide(color: cyan, width: 1.5),
        ),
        errorBorder: inputShape.copyWith(borderSide: BorderSide(color: danger)),
        focusedErrorBorder: inputShape.copyWith(
          borderSide: BorderSide(color: danger, width: 1.5),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: cyan,
          foregroundColor: colors.onPrimary,
          disabledBackgroundColor: surfaceRaised,
          disabledForegroundColor: textTertiary,
          minimumSize: const Size.fromHeight(48),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(controlRadius),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: text,
          minimumSize: const Size.fromHeight(46),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
          side: BorderSide(color: outline),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(controlRadius),
          ),
        ),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: surfaceSunken,
        selectedIconTheme: IconThemeData(color: cyan),
        unselectedIconTheme: IconThemeData(color: textTertiary),
        selectedLabelTextStyle: textTheme.labelMedium!.copyWith(color: cyan),
        unselectedLabelTextStyle: textTheme.labelMedium!.copyWith(
          color: textTertiary,
        ),
        indicatorColor: cyan.withValues(alpha: .16),
        indicatorShape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(controlRadius),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 72,
        backgroundColor: surfaceSunken,
        indicatorColor: cyan.withValues(alpha: .16),
        surfaceTintColor: Colors.transparent,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => textTheme.labelMedium!.copyWith(
            color: states.contains(WidgetState.selected) ? cyan : textTertiary,
          ),
        ),
        iconTheme: WidgetStateProperty.resolveWith(
          (states) => IconThemeData(
            color: states.contains(WidgetState.selected) ? cyan : textTertiary,
          ),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: surfaceRaised,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(sectionRadius),
          side: BorderSide(color: outline),
        ),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: cyan,
        linearTrackColor: surfaceMuted,
      ),
      dividerTheme: DividerThemeData(color: divider, space: 1),
    );
  }
}

class _AletheiaPalette {
  const _AletheiaPalette({
    required this.canvas,
    required this.surface,
    required this.surfaceRaised,
    required this.surfaceSunken,
    required this.surfaceMuted,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.border,
    required this.divider,
    required this.cyan,
    required this.mint,
    required this.warning,
    required this.danger,
    required this.mapPointCloud,
    required this.mapVirtualWall,
    required this.mapRobot,
    required this.mapRobotOutline,
    required this.onPrimary,
    required this.onSecondary,
    required this.primaryContainer,
    required this.secondaryContainer,
    required this.errorContainer,
    required this.onError,
  });

  final Color canvas;
  final Color surface;
  final Color surfaceRaised;
  final Color surfaceSunken;
  final Color surfaceMuted;
  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color border;
  final Color divider;
  final Color cyan;
  final Color mint;
  final Color warning;
  final Color danger;
  final Color mapPointCloud;
  final Color mapVirtualWall;
  final Color mapRobot;
  final Color mapRobotOutline;
  final Color onPrimary;
  final Color onSecondary;
  final Color primaryContainer;
  final Color secondaryContainer;
  final Color errorContainer;
  final Color onError;
}
