import 'package:aletheia_mobile/app/responsive_layout.dart';
import 'package:test/test.dart';

void main() {
  test('uses a side rail on a landscape phone to preserve vertical space', () {
    expect(usesNavigationRail(availableWidth: 844, isLandscape: true), isTrue);
    expect(
      usesNavigationRail(availableWidth: 430, isLandscape: false),
      isFalse,
    );
  });

  test('uses two panes only when landscape content has enough room', () {
    expect(
      usesTwoColumnWorkspace(availableWidth: 760, isLandscape: true),
      isTrue,
    );
    expect(
      usesTwoColumnWorkspace(availableWidth: 640, isLandscape: true),
      isFalse,
    );
  });

  test('keeps map and camera workspaces usable on short landscape screens', () {
    expect(isCompactLandscape(viewportHeight: 390, isLandscape: true), isTrue);
    expect(
      observationWorkspaceHeight(viewportHeight: 390, isLandscape: true),
      378,
    );
    expect(
      isCompactLandscape(viewportHeight: 900, isLandscape: false),
      isFalse,
    );
  });
}
