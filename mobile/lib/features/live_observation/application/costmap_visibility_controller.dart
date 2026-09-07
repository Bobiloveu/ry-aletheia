import 'package:flutter_riverpod/flutter_riverpod.dart';

/// A handset-only preference for the local costmap display layer.
///
/// It cannot alter robot telemetry, navigation, or any safety setting.
final costmapVisibilityProvider =
    NotifierProvider.autoDispose<CostmapVisibilityController, bool>(
      CostmapVisibilityController.new,
    );

class CostmapVisibilityController extends Notifier<bool> {
  @override
  bool build() => true;

  void toggle() => state = !state;
}
