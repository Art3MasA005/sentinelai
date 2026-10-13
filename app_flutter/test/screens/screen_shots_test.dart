// Renders auth screens with real fonts into test/screens/shots/*.png for visual review.
// Run: flutter test test/screens --update-goldens
@Tags(['screens'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelai/core/api/api_client.dart';
import 'package:sentinelai/core/state.dart';
import 'package:sentinelai/core/theme.dart';
import 'package:sentinelai/features/auth/splash_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _loadFonts() async {
  final root =
      '${Platform.environment['FLUTTER_ROOT'] ?? r'C:\flutter_windows_3.41.6-stable\flutter'}'
      r'\bin\cache\artifacts\material_fonts';
  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    for (final f in files) {
      final bytes = File('$root\\$f').readAsBytesSync();
      loader.addFont(Future.value(ByteData.view(bytes.buffer)));
    }
    await loader.load();
  }

  await load('Roboto', ['roboto-regular.ttf', 'roboto-medium.ttf', 'roboto-bold.ttf', 'roboto-black.ttf']);
  await load('MaterialIcons', ['materialicons-regular.otf']);
}

Future<void> _shoot(WidgetTester tester, Palette palette, MockClient client, String name, Duration at) async {
  tester.view.physicalSize = const Size(1400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  AppColors.current = palette;
  await tester.pumpWidget(
    ProviderScope(
      retry: (_, _) => null,
      overrides: [
        prefsProvider.overrideWithValue(prefs),
        apiProvider.overrideWithValue(ApiClient(baseUrl: 'http://127.0.0.1:8765', client: client)),
      ],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: buildTheme(palette).copyWith(textTheme: buildTheme(palette).textTheme.apply(fontFamily: 'Roboto')),
        home: const SplashScreen(),
      ),
    ),
  );
  // Advance in frames so animations and the boot sequence actually progress.
  for (var t = Duration.zero; t < at; t += const Duration(milliseconds: 50)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  await expectLater(find.byType(MaterialApp), matchesGoldenFile('shots/$name.png'));
  // Let the fake backend's pending replies finish so the test ends cleanly.
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 31));
}

http.Response _json(Object b, [int c = 200]) =>
    http.Response(jsonEncode(b), c, headers: {'content-type': 'application/json'});

void main() {
  setUpAll(_loadFonts);

  // Backend that never answers config, so the splash stays on "Checking…" for the picture.
  final slow = MockClient((r) async {
    if (r.url.path.endsWith('/health')) return _json({'status': 'ok'});
    await Future<void>.delayed(const Duration(seconds: 30));
    return _json({});
  });
  final down = MockClient((r) async => throw http.ClientException('refused'));

  for (final p in [Palette.dark, Palette.light]) {
    final theme = p.glass ? 'light' : 'dark';
    testWidgets(
      'splash loading $theme',
      (t) => _shoot(t, p, slow, 'splash_loading_$theme', const Duration(milliseconds: 2800)),
    );
    testWidgets(
      'splash offline $theme',
      (t) => _shoot(t, p, down, 'splash_offline_$theme', const Duration(milliseconds: 2800)),
    );
  }
}
