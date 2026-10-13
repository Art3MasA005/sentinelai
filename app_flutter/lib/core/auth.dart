import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/api_client.dart';
import 'api/models.dart';
import 'backend_launcher.dart';
import 'state.dart';

/// Session token issued by the backend at sign-in; persisted so the app reopens signed in.
class SessionToken extends Notifier<String?> {
  @override
  String? build() => ref.read(prefsProvider).getString('sessionToken');

  void set(String? token) {
    state = token;
    final p = ref.read(prefsProvider);
    token == null ? p.remove('sessionToken') : p.setString('sessionToken', token);
  }
}

final sessionTokenProvider = NotifierProvider<SessionToken, String?>(SessionToken.new);

enum AuthPhase { booting, offline, signedOut, signedIn }

class AuthState {
  const AuthState({
    this.phase = AuthPhase.booting,
    this.step = 'Starting…',
    this.progress = 0,
    this.user,
    this.config,
    this.error,
  });

  final AuthPhase phase;
  final String step; // what the splash screen is doing right now
  final double progress;
  final Json? user;
  final Json? config; // /auth/config: auth_required, google_enabled, roles…
  final String? error;

  bool get authRequired => config?['auth_required'] == true;

  AuthState copyWith({AuthPhase? phase, String? step, double? progress, Json? user, Json? config, String? error}) =>
      AuthState(
        phase: phase ?? this.phase,
        step: step ?? this.step,
        progress: progress ?? this.progress,
        user: user ?? this.user,
        config: config ?? this.config,
        error: error,
      );
}

class AuthController extends Notifier<AuthState> {
  /// The splash brand animation (SplashScreen.intro, 2.6 s) plus a short hold on its final frame.
  static const minSplash = Duration(milliseconds: 2900);

  @override
  AuthState build() => const AuthState();

  ApiClient get _api => ref.read(apiProvider);

  int _bootRun = 0;

  /// Splash sequence: backend reachable → sign-in options → existing session.
  /// A newer boot (Retry) or disposal makes an in-flight one stop updating state.
  Future<void> boot() async {
    final run = ++_bootRun;
    bool stale() => !ref.mounted || run != _bootRun;
    final started = DateTime.now();
    state = const AuthState(step: 'Connecting to local backend…', progress: 0.15);
    try {
      await _reachBackend(stale);
      if (stale()) return;
      if (stale()) return;
      state = state.copyWith(step: 'Loading sign-in options…', progress: 0.45);
      final Json config;
      try {
        config = await _api.authConfig();
      } on ApiException catch (e) {
        // An older backend process (started before accounts existed) has no /auth routes.
        if (e.status == 404) {
          throw ApiException('The running backend is outdated — stop it (Ctrl+C) and start it again.', status: 404);
        }
        rethrow;
      }
      if (stale()) return;
      state = state.copyWith(config: config, step: 'Checking your session…', progress: 0.75);
      Json? user;
      if (ref.read(sessionTokenProvider) != null) {
        try {
          user = await _api.me();
        } on ApiException catch (e) {
          if (stale()) return;
          if (e.status == 401) ref.read(sessionTokenProvider.notifier).set(null); // expired or revoked
        }
      }
      if (stale()) return;
      state = state.copyWith(user: user, step: user == null ? 'Ready' : 'Welcome back, ${user['name']}', progress: 1);
      final left = minSplash - DateTime.now().difference(started);
      if (left > Duration.zero) await Future<void>.delayed(left);
      if (stale()) return;
      state = state.copyWith(phase: user == null ? AuthPhase.signedOut : AuthPhase.signedIn);
    } on ApiException catch (e) {
      final left = const Duration(milliseconds: 900) - DateTime.now().difference(started);
      if (left > Duration.zero) await Future<void>.delayed(left);
      if (stale()) return;
      state = state.copyWith(phase: AuthPhase.offline, error: e.message, step: 'Backend unreachable', progress: 0);
    }
  }

  /// Health check; if a local backend is not running, the desktop app starts it and waits for it.
  Future<void> _reachBackend(bool Function() stale) async {
    try {
      await _api.health();
      return;
    } on ApiException catch (e) {
      // Only "nothing answered" is fixed by starting a backend; an HTTP error means one is running.
      final uri = Uri.tryParse(_api.baseUrl);
      final local = uri != null && (uri.host == '127.0.0.1' || uri.host == 'localhost');
      if (e.status != null || !local || !await BackendLauncher.start(uri.port)) rethrow;
    }
    state = state.copyWith(step: 'Starting local backend…', progress: 0.3);
    final deadline = DateTime.now().add(const Duration(seconds: 40));
    while (true) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      if (stale()) return;
      try {
        await _api.health();
        return;
      } on ApiException {
        if (DateTime.now().isAfter(deadline)) rethrow;
      }
    }
  }

  /// Store a session returned by /auth/login, /auth/signup or /auth/google.
  void acceptSession(Json session) {
    ref.read(sessionTokenProvider.notifier).set(session['token'] as String);
    state = state.copyWith(phase: AuthPhase.signedIn, user: asJson(session['user']));
  }

  void updateUser(Json user) => state = state.copyWith(user: user);

  Future<void> signOut() async {
    try {
      await _api.logout();
    } catch (_) {
      // Offline or already expired: the local sign-out below is what matters.
    }
    ref.read(sessionTokenProvider.notifier).set(null);
    state = AuthState(phase: AuthPhase.signedOut, config: state.config, step: 'Signed out', progress: 1);
  }
}

final authProvider = NotifierProvider<AuthController, AuthState>(AuthController.new);
