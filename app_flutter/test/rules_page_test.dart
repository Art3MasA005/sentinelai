import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelai/core/api/api_client.dart';
import 'package:sentinelai/core/state.dart';
import 'package:sentinelai/core/theme.dart';
import 'package:sentinelai/features/rules/rules_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _body() => {
  'window_size': 2000,
  'openworld': {'method': 'msp+centroid', 'msp_quantile': 0.02, 'distance_quantile': 0.99},
  'drift': {
    'detectors': ['ks', 'confidence'],
    'ks_alpha': 0.01,
    'ks_threshold': 0.3,
    'psi_threshold': 0.2,
    'confidence_threshold': 0.1,
    'cooldown_windows': 2,
    'reference_update': 'on_adaptation',
    'max_reference_rows': 5000,
  },
  'labels': {'delay_windows': 1, 'budget': 1.0},
  'adaptation': {
    'method': 'static',
    'trigger': 'drift_or_novelty',
    'validation_guard': true,
    'reference_guard': true,
    'rollback': true,
    'min_gain': 0.0,
    'max_forgetting': 0.05,
    'rollback_margin': 0.05,
  },
};

void main() {
  testWidgets('editing a rule validates input and saves a new policy version', (tester) async {
    tester.view.physicalSize = const Size(1600, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    http.Request? saved;
    var version = 1;
    final client = MockClient((r) async {
      http.Response json(Object b, [int c = 200]) =>
          http.Response(jsonEncode(b), c, headers: {'content-type': 'application/json'});
      final policy = {
        'version': version,
        'policy_id': 'POL-00$version',
        'status': 'active',
        'note': version == 1 ? 'Initial default policy' : 'Tighter review budget',
        'updated_by': 'Researcher',
        'created_at': '2026-10-11T10:00:00Z',
        'body': saved == null ? _body() : jsonDecode(saved!.body)['body'],
      };
      if (r.url.path.endsWith('/policies/active')) return json(policy);
      if (r.url.path.endsWith('/policies') && r.method == 'GET') return json([policy]);
      if (r.url.path.endsWith('/policies') && r.method == 'POST') {
        saved = r;
        version = 2;
        return json({...policy, 'version': 2, 'body': jsonDecode(r.body)['body']}, 201);
      }
      return json({'detail': 'nope'}, 404);
    });
    AppColors.current = Palette.light;
    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [
          prefsProvider.overrideWithValue(prefs),
          apiProvider.overrideWithValue(ApiClient(baseUrl: 'http://fake', client: client)),
        ],
        child: MaterialApp(
          theme: buildTheme(Palette.light),
          home: const Scaffold(body: RulesPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('POL-001 active'), findsOneWidget);
    final save = find.widgetWithText(FilledButton, 'Save as new version');
    expect(tester.widget<FilledButton>(save).onPressed, isNull); // nothing changed yet

    // Out-of-range value: error shown, save disabled.
    expect(find.widgetWithText(TextFormField, '0.02'), findsOneWidget);
    final budget = find.byType(TextFormField).first; // False alarm budget (msp_quantile)
    await tester.enterText(budget, '0.9');
    await tester.pump();
    expect(find.text('≤ 0.5'), findsOneWidget);
    expect(tester.widget<FilledButton>(save).onPressed, isNull);

    // Valid value + toggle, then save with a note.
    await tester.enterText(budget, '0.05');
    await tester.tap(find.byType(Switch).at(2)); // rollback on degradation -> off
    await tester.pump();
    expect(tester.widget<FilledButton>(save).onPressed, isNotNull);
    await tester.tap(save);
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'Tighter review budget');
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();

    final sent = jsonDecode(saved!.body) as Map<String, dynamic>;
    expect(sent['note'], 'Tighter review budget');
    expect(sent['body']['openworld']['msp_quantile'], 0.05);
    expect(sent['body']['adaptation']['rollback'], false);
    expect(sent['body']['window_size'], 2000); // untouched values preserved
    expect(find.text('POL-002 active'), findsOneWidget);
  });
}
