import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelai/core/api/api_client.dart';
import 'package:sentinelai/core/state.dart';
import 'package:sentinelai/core/theme.dart';
import 'package:sentinelai/features/experiments/experiments_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Fake backend: records every request and answers like the FastAPI server.
class FakeBackend {
  final requests = <http.Request>[];
  bool validated = false;
  final runs = <Map<String, dynamic>>[];

  Map<String, dynamic> _run(String status) => {
    'run_id': 'run-x',
    'seq': 7,
    'name': 'Selective adaptation · DEMO',
    'status': status,
    'method': 'guarded_selective',
    'dataset_id': 'DEMO_sentinel_synthetic',
    'data_origin': 'demo',
    'config': {},
    'progress': {'phase': 'queued', 'window': 0, 'total_windows': 0},
    'created_at': '2026-10-11T10:00:00Z',
    'started_at': status == 'running' ? '2026-10-11T10:00:01Z' : null,
    'summary': null,
  };

  Future<http.Response> handle(http.Request r) async {
    requests.add(r);
    final p = r.url.path;
    http.Response json(Object body, [int code = 200]) =>
        http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json'});
    if (p.endsWith('/datasets')) {
      return json({
        'items': [
          {
            'id': 'DEMO_sentinel_synthetic',
            'name': 'DEMO',
            'path': '',
            'files': ['DEMO_flows.csv'],
            'size_bytes': 1,
            'data_origin': 'demo',
            'is_demo': true,
            'detected_profile': 'sentinel_demo',
            'last_validation': validated ? {'profile': 'sentinel_demo', 'valid': true, 'rows': 30000} : null,
          },
        ],
        'total': 1,
        'page': 1,
        'page_size': 500,
      });
    }
    if (p.endsWith('/datasets/validate')) {
      validated = true;
      return json({'dataset_id': 'DEMO_sentinel_synthetic', 'valid': true, 'errors': [], 'warnings': []});
    }
    if (p.endsWith('/policies/active')) {
      return json({
        'version': 3,
        'body': {'window_size': 1000},
      });
    }
    if (p.endsWith('/experiments/batch')) {
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      final n = (body['seeds'] as List).length * ((body['methods'] as List?)?.length ?? 1);
      for (var i = 0; i < n; i++) {
        runs.add({..._run('queued'), 'run_id': 'run-b$i', 'seq': 10 + i, 'group_id': 'grp-1'});
      }
      return json({'group_id': 'grp-1', 'runs': runs}, 201);
    }
    if (p.endsWith('/experiments') && r.method == 'POST') {
      runs.add(_run('created'));
      return json(runs.last, 201);
    }
    if (p.endsWith('/experiments') && r.method == 'GET') {
      return json({'items': runs, 'total': runs.length, 'page': 1, 'page_size': 200});
    }
    if (p.endsWith('/start')) {
      runs[0] = _run('running');
      return json(runs[0], 202);
    }
    return json({'detail': 'not found'}, 404);
  }
}

void main() {
  testWidgets('Create & start validates, applies the active policy and starts the run', (tester) async {
    tester.view.physicalSize = const Size(1600, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final backend = FakeBackend();
    final api = ApiClient(baseUrl: 'http://fake', client: MockClient(backend.handle));
    AppColors.current = Palette.dark;

    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [prefsProvider.overrideWithValue(prefs), apiProvider.overrideWithValue(api)],
        child: MaterialApp(
          theme: buildTheme(Palette.dark),
          home: const Scaffold(body: ExperimentsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('Not validated yet'), findsOneWidget);

    await tester.tap(find.text('Create & start'));
    // The started run shows an indeterminate progress bar, so the UI never "settles"; pump instead.
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    final paths = backend.requests.map((r) => '${r.method} ${r.url.path}').toList();
    final validateAt = paths.indexOf('POST /api/v1/datasets/validate');
    final createAt = paths.indexOf('POST /api/v1/experiments');
    final startAt = paths.indexOf('POST /api/v1/experiments/run-x/start');
    expect(validateAt, greaterThanOrEqualTo(0), reason: 'dataset must be validated before the run');
    expect(createAt, greaterThan(validateAt));
    expect(startAt, greaterThan(createAt));

    final body = jsonDecode(backend.requests[createAt].body) as Map<String, dynamic>;
    expect(body['dataset_id'], 'DEMO_sentinel_synthetic');
    expect(body['policy_version'], 3);
    expect(body['adaptation'], {'method': 'nova'});
    expect(body['model'], {'kind': 'hist_gb'});
    expect(body['seed'], 42);
    expect(find.textContaining('RUN-007 started'), findsOneWidget);
  });

  test('parseSeeds accepts one or many whole numbers', () {
    expect(parseSeeds('42'), [42]);
    expect(parseSeeds('42, 43 44'), [42, 43, 44]);
    expect(parseSeeds('42, 42'), [42]);
    expect(parseSeeds('4x'), isNull);
    expect(parseSeeds('  '), isNull);
  });

  testWidgets('several seeds + all methods creates one batch request', (tester) async {
    tester.view.physicalSize = const Size(1600, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final backend = FakeBackend()..validated = true;
    final api = ApiClient(baseUrl: 'http://fake', client: MockClient(backend.handle));
    AppColors.current = Palette.dark;
    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [prefsProvider.overrideWithValue(prefs), apiProvider.overrideWithValue(api)],
        child: MaterialApp(
          theme: buildTheme(Palette.dark),
          home: const Scaffold(body: ExperimentsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '42'), '1, 2, 3');
    await tester.tap(find.byType(Checkbox).first); // run every method
    await tester.pump();
    expect(find.textContaining('27 runs'), findsOneWidget); // 9 methods x 3 seeds
    await tester.tap(find.text('Create & start'));
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    final req = backend.requests.firstWhere((r) => r.url.path.endsWith('/experiments/batch'));
    final body = jsonDecode(req.body) as Map<String, dynamic>;
    expect(body['seeds'], [1, 2, 3]);
    expect((body['methods'] as List).length, 9);
    expect(body['start'], true);
    expect(body['base']['policy_version'], 3);
    expect(backend.requests.where((r) => r.url.path.endsWith('/start')), isEmpty);
  });
}
