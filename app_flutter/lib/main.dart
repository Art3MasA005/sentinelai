import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/auth.dart';
import 'core/dialogs.dart';
import 'core/shell.dart';
import 'core/state.dart';
import 'core/theme.dart';
import 'features/auth/splash_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  runApp(
    ProviderScope(
      // Errors are shown in the UI (e.g. backend offline); the shell's timers drive re-fetching.
      retry: (_, _) => null,
      overrides: [prefsProvider.overrideWithValue(prefs)],
      child: const SentinelApp(),
    ),
  );
}

class SentinelApp extends ConsumerWidget {
  const SentinelApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(settingsProvider).themeMode;
    final platformDark = MediaQuery.platformBrightnessOf(context) == Brightness.dark;
    final palette = switch (mode) {
      'light' => Palette.light,
      'system' => platformDark ? Palette.dark : Palette.light,
      _ => Palette.dark,
    };
    // Widgets read AppColors directly, so the tree is rebuilt from scratch on a theme switch.
    AppColors.current = palette;
    return MaterialApp(
      key: ValueKey(palette.brightness),
      title: 'SentinelAI',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(palette),
      // Dialogs blur a snapshot of everything below them (see core/dialogs.dart).
      builder: (context, child) => RepaintBoundary(key: appSnapshotKey, child: child),
      home: const AuthGate(),
    );
  }
}

/// Splash while booting (or when the backend is unreachable), then the app.
class AuthGate extends ConsumerWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final phase = ref.watch(authProvider.select((s) => s.phase));
    final splash = phase == AuthPhase.booting || phase == AuthPhase.offline;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 500),
      child: splash
          ? const SplashScreen(key: ValueKey('splash'))
          // Signed-out users still reach the app while sign-in is optional (SENTINEL_AUTH_REQUIRED=false).
          : const AppShell(key: ValueKey('app')),
    );
  }
}
