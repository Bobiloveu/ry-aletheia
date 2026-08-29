import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/system_maintenance_repository.dart';

final systemMaintenanceRepositoryProvider =
    Provider<SystemMaintenanceRepository>(
      (ref) =>
          SystemMaintenanceRepository(ref.watch(aletheiaApiClientProvider)),
    );
