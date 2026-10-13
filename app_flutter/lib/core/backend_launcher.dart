import 'dart:io';

import 'package:flutter/foundation.dart';

/// Starts the local Python backend when the desktop app finds none running, so the installed app works
/// with a double-click. It runs without a console window (pythonw) and logs to `backend.log` in its folder.
/// The app stops it again on exit, but only if it started it.
///
/// The backend folder comes from `sentinelai.ini` next to the exe (`BackendDir=...`, written by the
/// installer), else the SENTINELAI_BACKEND environment variable, else a `backend` folder found by walking
/// up from the exe (a development build inside the repository).
class BackendLauncher {
  BackendLauncher._();

  static Process? _started;

  static bool get supported => !kIsWeb && Platform.isWindows;

  /// Whether this app instance started the backend (and should stop it on exit).
  static bool get ownsBackend => _started != null;

  static Directory? backendDir() {
    if (!supported) return null;
    bool usable(Directory d) => File('${d.path}\\.venv\\Scripts\\pythonw.exe').existsSync();
    final exeDir = File(Platform.resolvedExecutable).parent;
    final ini = File('${exeDir.path}\\sentinelai.ini');
    if (ini.existsSync()) {
      for (final line in ini.readAsLinesSync()) {
        final m = RegExp(r'^\s*BackendDir\s*=\s*(.+?)\s*$', caseSensitive: false).firstMatch(line);
        if (m != null && usable(Directory(m.group(1)!))) return Directory(m.group(1)!);
      }
    }
    final env = Platform.environment['SENTINELAI_BACKEND'];
    if (env != null && usable(Directory(env))) return Directory(env);
    for (Directory d = exeDir; d.parent.path != d.path; d = d.parent) {
      final b = Directory('${d.path}\\backend');
      if (usable(b)) return b;
    }
    return null;
  }

  /// Starts the backend on [port] if a backend folder is known. Returns false if it cannot.
  static Future<bool> start(int port) async {
    if (_started != null) return true;
    final dir = backendDir();
    if (dir == null) return false;
    try {
      _started = await Process.start(
        '${dir.path}\\.venv\\Scripts\\pythonw.exe',
        ['-m', 'app.cli', 'serve', '--port', '$port', '--log-file', '${dir.path}\\backend.log'],
        workingDirectory: dir.path,
        mode: ProcessStartMode.detached,
      );
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Stops the backend this app started (no-op otherwise).
  static void stop() {
    final p = _started;
    if (p == null) return;
    _started = null;
    Process.killPid(p.pid);
  }
}
