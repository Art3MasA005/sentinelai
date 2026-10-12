import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelai/core/api/api_client.dart';
import 'package:sentinelai/core/auth.dart';
import 'package:sentinelai/core/state.dart';
import 'package:sentinelai/core/theme.dart';
import 'package:sentinelai/features/auth/splash_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<ProviderContainer> _pump(WidgetTester tester, MockClient client, {Map<String, Object> prefs = const {}}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues(prefs);
  final p = await SharedPreferences.getInstance();
  AppColors.current = Palette.dark;
  final container = ProviderContainer(
    retry: (_, _) => null,
    overrides: [
      prefsProvider.overrideWithValue(p),
      apiProvider.overrideWith(
        (ref) => ApiClient(baseUrl: 'http://fake', token: ref.watch(sessionTokenProvider), client: client),
      ),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: buildTheme(Palette.dark), home: const SplashScreen()),
    ),
  );
  return container;
}

http.Response _json(Object b, [int code = 200]) =>
    http.Response(jsonEncode(b), code, headers: {'content-type': 'application/json'});

void main() {
  testWidgets('boots: backend → config → saved session → signed in', (tester) async {
    final seen = <String>[];
    final client = MockClient((r) async {
      seen.add('${r.url.path} ${r.headers['authorization'] ?? '-'}');
      if (r.url.path.endsWith('/health')) return _json({'status': 'ok', 'version': '0.1.0'});
      if (r.url.path.endsWith('/auth/config')) return _json({'auth_required': false, 'google_enabled': false});
      if (r.url.path.endsWith('/auth/me')) return _json({'id': 1, 'name': 'Ayesha', 'email': 'a@x.org'});
      return _json({'detail': 'nope'}, 404);
    });
    final c = await _pump(tester, client, prefs: {'sessionToken': 'tok123'});
    expect(find.text('SentinelAI'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 100));
    expect(c.read(authProvider).phase, AuthPhase.booting); // splash stays up for its minimum time
    await tester.pump(AuthController.minSplash);
    expect(c.read(authProvider).phase, AuthPhase.signedIn);
    expect(c.read(authProvider).user!['name'], 'Ayesha');
    expect(seen.last, '/api/v1/auth/me Bearer tok123');
  });

  testWidgets('expired session is cleared and the user is signed out', (tester) async {
    final client = MockClient((r) async {
      if (r.url.path.endsWith('/health')) return _json({'status': 'ok'});
      if (r.url.path.endsWith('/auth/config')) return _json({'auth_required': true});
      return _json({'detail': 'Sign in required.'}, 401);
    });
    final c = await _pump(tester, client, prefs: {'sessionToken': 'old'});
    await tester.pump(AuthController.minSplash + const Duration(milliseconds: 100));
    expect(c.read(authProvider).phase, AuthPhase.signedOut);
    expect(c.read(authProvider).authRequired, isTrue);
    expect(c.read(sessionTokenProvider), isNull);
  });

  testWidgets('offline backend shows help and retries', (tester) async {
    var up = false;
    final client = MockClient((r) async {
      if (!up) throw http.ClientException('connection refused');
      if (r.url.path.endsWith('/health')) return _json({'status': 'ok'});
      return _json({'auth_required': false});
    });
    final c = await _pump(tester, client);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(milliseconds: 400));
    expect(c.read(authProvider).phase, AuthPhase.offline);
    expect(find.textContaining('reach the backend'), findsOneWidget);
    expect(find.textContaining('app.cli serve'), findsOneWidget);
    up = true;
    await tester.tap(find.text('Retry'));
    await tester.pump(AuthController.minSplash + const Duration(milliseconds: 100));
    expect(c.read(authProvider).phase, AuthPhase.signedOut);
  });
}
