import 'dart:async';
import 'dart:convert';

import 'package:aletheia_mobile/app/app.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('竖屏下可完成机器人观测与工具全路径', (tester) async {
    await SharedPreferences.getInstance().then(
      (preferences) => preferences.clear(),
    );
    addTearDown(() async {
      await SharedPreferences.getInstance().then(
        (preferences) => preferences.clear(),
      );
    });

    runApp(
      ProviderScope(
        overrides: [
          aletheiaApiClientProvider.overrideWithValue(
            AletheiaApiClient(_DemoRobotClient()),
          ),
        ],
        child: const AletheiaApp(),
      ),
    );
    await tester.pumpAndSettle();

    Future<void> tapAndSettle(Finder finder) async {
      await tester.ensureVisible(finder);
      await tester.pump();
      await tester.tap(finder);
      await tester.pumpAndSettle();
    }

    expect(find.text('连接或确认机器人'), findsOneWidget);
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(
      find.text('输入机器人地址，例如 192.168.1.20、robot.local 或 [fe80::1]。'),
      findsOneWidget,
    );

    await tester.tap(find.byType(TextField).first);
    await tester.enterText(find.byType(TextField).first, 'demo.robot');
    await tapAndSettle(find.text('连接并检查'));
    expect(find.text('机器人已连接'), findsOneWidget);

    await tapAndSettle(find.text('观测'));
    expect(find.text('查看地图与相机'), findsOneWidget);
    expect(find.text('活动地图'), findsOneWidget);
    expect(find.text('实时位置'), findsOneWidget);
    expect(find.text('点云'), findsOneWidget);

    await tapAndSettle(find.text('相机').first);
    expect(find.text('相机'), findsAtLeast(1));
    expect(find.text('正在等待画面。'), findsOneWidget);
    expect(find.text('停止此路视频'), findsOneWidget);

    await tapAndSettle(find.text('工具'));
    expect(find.text('机器人工作台'), findsOneWidget);

    await tapAndSettle(find.text('打开测试'));
    expect(find.text('创建与跟踪自动化验证'), findsOneWidget);
    expect(find.text('创建测试计划'), findsOneWidget);

    await tapAndSettle(find.text('浏览用例库'));
    expect(find.text('浏览可执行测试内容'), findsOneWidget);
    expect(find.text('走廊巡检'), findsOneWidget);

    await tapAndSettle(find.text('用于测试'));
    expect(find.text('创建测试计划'), findsOneWidget);
    expect(find.text('走廊巡检'), findsOneWidget);

    await tapAndSettle(find.byTooltip('返回工具'));
    await tapAndSettle(find.text('查看日志'));
    expect(find.text('诊断日志'), findsOneWidget);
    expect(find.text('演示数据已加载'), findsOneWidget);

    await tapAndSettle(find.byTooltip('返回工具'));
    await tapAndSettle(find.text('查看报告'));
    expect(find.text('测试报告'), findsOneWidget);
    expect(find.text('demo_report.html'), findsOneWidget);
  });
}

/// Deliberately read-only, in-memory API fixture for the portrait device journey.
/// It exercises presentation and navigation only; no robot connection,
/// telemetry socket, WHEP session, or test creation leaves the test process.
class _DemoRobotClient extends http.BaseClient {
  static const _mapPreview = <int>[
    137,
    80,
    78,
    71,
    13,
    10,
    26,
    10,
    0,
    0,
    0,
    13,
    73,
    72,
    68,
    82,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    1,
    8,
    6,
    0,
    0,
    0,
    31,
    21,
    196,
    137,
    0,
    0,
    0,
    13,
    73,
    68,
    65,
    84,
    8,
    215,
    99,
    248,
    255,
    255,
    63,
    0,
    5,
    254,
    2,
    254,
    220,
    204,
    89,
    231,
    0,
    0,
    0,
    0,
    73,
    69,
    78,
    68,
    174,
    66,
    96,
    130,
  ];

  static const _observation = {
    'enabled': true,
    'telemetry': {'online': true, 'websocket_port': 8768, 'detail': '演示实时数据'},
    'preprocessor': {'available': true, 'managed': true},
    'active_map_id': 'demo-map',
    'idle_stop_seconds': 30,
  };

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final path = request.url.path;
    if (path.endsWith('/preview.png')) {
      return http.StreamedResponse(
        Stream<List<int>>.value(_mapPreview),
        200,
        headers: const {'content-type': 'image/png'},
      );
    }

    final payload = switch (path) {
      '/api/observation' ||
      '/api/observation/start' ||
      '/api/observation/heartbeat' => _observation,
      '/api/observation/active-map' => {'active_map_id': 'demo-map'},
      '/api/observation/maps/demo-map/layers' => {
        'map': {
          'width': 100,
          'height': 75,
          'resolution': 0.05,
          'origin': [-2.5, -1.875],
          'frame_id': 'map',
        },
        'virtual_walls': [
          {
            'coordinate_mode': 'world',
            'points': [
              {'x': -1.2, 'y': -1.0},
              {'x': .4, 'y': -1.0},
            ],
          },
        ],
      },
      '/api/settings' => {
        'live_observation': {
          'active_vehicle_model': 'demo-robot',
          'vehicle_models': [
            {'id': 'demo-robot', 'length_m': 1.0, 'width_m': .68},
          ],
        },
      },
      '/api/video/status' || '/api/video/control' => {
        'enabled': true,
        'gateway': {'online': true, 'detail': '演示视频服务'},
        'streams': [
          for (final name in [
            'front_camera',
            'back_camera',
            'left_camera',
            'right_camera',
            'detection_camera',
            'segmentation_overlay',
          ])
            {
              'name': name,
              'enabled': true,
              'status': 'waiting',
              'resolution': '1280 × 960',
              'fps': 30,
              'source_topic': '演示相机',
              'codec': 'H.264',
              'url': 'http://demo.robot:8087/whep/$name',
            },
        ],
      },
      '/api/cases' => {
        'cases': [
          {
            'id': 'demo-corridor-check',
            'filename': 'corridor_check.yaml',
            'name': '走廊巡检',
            'alias': '走廊巡检',
            'parameters': {
              'community': '演示园区',
              'building': 1,
              'unit': 1,
              'floor': 1,
              'door': 101,
            },
            'management': {
              'lifecycle': 'active',
              'version': '1.0.0',
              'summary': '验证机器人在走廊中的运行表现。',
              'tags': ['日常巡检'],
            },
          },
        ],
        'validationIssues': const [],
      },
      '/api/runs/latest' => {'run': null},
      '/api/tool-logs' => {
        'entries': [
          {
            'time': '2026-08-27 10:00',
            'level': 'INFO',
            'source': '演示',
            'message': '演示数据已加载',
            'exception': '',
          },
        ],
      },
      '/api/reports' => {
        'reports': [
          {
            'filename': 'demo_report.html',
            'size': 1024,
            'modified_at': '2026-08-27T10:00:00+08:00',
            'csv_filename': 'demo_report.csv',
          },
        ],
      },
      _ => {'error': '演示接口未配置：$path'},
    };

    return http.StreamedResponse(
      Stream<List<int>>.value(utf8.encode(jsonEncode(payload))),
      payload.containsKey('error') ? 404 : 200,
      headers: const {'content-type': 'application/json'},
    );
  }
}
