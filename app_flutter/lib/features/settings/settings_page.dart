import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/glass_menu.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  late final TextEditingController _url = TextEditingController(text: ref.read(settingsProvider).baseUrl);
  String? _urlError;
  String? _testResult;
  bool _testOk = false;
  bool _testing = false;

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  void _update(AppSettings Function(AppSettings) f) =>
      ref.read(settingsProvider.notifier).update(f(ref.read(settingsProvider)));

  Future<void> _testAndSave() async {
    final text = _url.text.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(text);
    if (uri == null || !uri.hasScheme || !uri.scheme.startsWith('http') || uri.host.isEmpty) {
      setState(() => _urlError = 'Use a full URL, e.g. http://127.0.0.1:8765');
      return;
    }
    setState(() {
      _urlError = null;
      _testing = true;
      _testResult = null;
    });
    final timeout = Duration(seconds: ref.read(settingsProvider).timeoutSeconds);
    final sw = Stopwatch()..start();
    try {
      final h = await ApiClient(baseUrl: text, timeout: timeout).health();
      sw.stop();
      _update((s) => s.copyWith(baseUrl: text));
      ref.invalidate(healthProvider);
      ref.read(refreshTickProvider.notifier).bump();
      setState(() {
        _testOk = h['status'] == 'ok';
        _testResult =
            '${_testOk ? 'Connected' : 'Reachable but degraded'} · SentinelAI ${h['version']} · '
            '${sw.elapsedMilliseconds} ms';
      });
    } catch (e) {
      setState(() {
        _testOk = false;
        _testResult = 'Not saved — $e';
      });
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(settingsProvider);
    final health = ref.watch(healthProvider);
    final ok = health.value?['status'] == 'ok';
    final paths = asPaths(health.value?['paths']);
    return PageScaffold(
      title: 'Settings',
      subtitle: 'Configure app preferences, local data paths, and API connectivity',
      children: [
        ResponsiveRow(
          children: [
            Panel(
              title: 'General preferences',
              child: Column(
                children: [
                  _Row(
                    'Application theme',
                    GlassSelect<String>(
                      label: '',
                      width: 260,
                      value: s.themeMode,
                      options: const {
                        'dark': 'Dark · Security console',
                        'light': 'Light · Frosted glass',
                        'system': 'Follow system',
                      },
                      onChanged: (v) => _update((x) => x.copyWith(themeMode: v)),
                    ),
                  ),
                  _Row(
                    'Default landing page',
                    GlassSelect<String>(
                      label: '',
                      width: 260,
                      value: s.landingPage,
                      options: {for (final p in AppPage.values) p.name: p.label},
                      onChanged: (v) => _update((x) => x.copyWith(landingPage: v)),
                    ),
                  ),
                  _Row(
                    'Time display',
                    GlassSelect<bool>(
                      label: '',
                      width: 260,
                      value: s.utc,
                      options: const {false: 'Local time', true: 'UTC'},
                      onChanged: (v) => _update((x) => x.copyWith(utc: v)),
                    ),
                  ),
                  _Row('Language', const _ReadOnly('English')),
                ],
              ),
            ),
            Panel(
              title: 'Backend connection',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _Row(
                    'API base URL',
                    SizedBox(
                      width: 260,
                      child: TextField(
                        controller: _url,
                        style: const TextStyle(fontSize: 13),
                        decoration: InputDecoration(errorText: _urlError, hintText: 'http://127.0.0.1:8765'),
                        onSubmitted: (_) => _testAndSave(),
                      ),
                    ),
                  ),
                  _Row('API version', const _ReadOnly(ApiClient.prefix)),
                  _Row(
                    'Request timeout',
                    GlassSelect<int>(
                      label: '',
                      width: 260,
                      value: s.timeoutSeconds,
                      options: const {5: '5 seconds', 10: '10 seconds', 30: '30 seconds', 60: '60 seconds'},
                      onChanged: (v) => _update((x) => x.copyWith(timeoutSeconds: v)),
                    ),
                  ),
                  _Row(
                    'Connection status',
                    SizedBox(
                      width: 260,
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: health.isLoading && !health.hasValue
                            ? Pill('Checking…', color: AppColors.textSecondary)
                            : ok
                            ? Pill('Connected', color: AppColors.green, icon: Icons.check_circle_outline)
                            : Pill('Offline', color: AppColors.red, icon: Icons.cloud_off),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: _testResult == null
                            ? Text('Changes apply after a successful connection test.', style: TextStyles.secondary)
                            : Text(
                                _testResult!,
                                style: TextStyle(color: _testOk ? AppColors.green : AppColors.red, fontSize: 12.5),
                              ),
                      ),
                      const SizedBox(width: 12),
                      FilledButton.icon(
                        onPressed: _testing ? null : _testAndSave,
                        icon: _testing
                            ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.wifi_tethering, size: 16),
                        label: const Text('Test & save'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
        ResponsiveRow(
          children: [
            Panel(
              title: 'Dataset & result directories',
              subtitle:
                  'Reported by the backend. Change them with SENTINEL_* environment variables before starting it.',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (health.hasError && !health.hasValue) ErrorNote(health.error!),
                  for (final (label, key) in const [
                    ('Dataset folder', 'datasets_dir'),
                    ('Experiment results', 'results_dir'),
                    ('Experiment configs', 'configs_dir'),
                    ('Database', 'db_path'),
                  ])
                    _PathField(label: label, path: paths[key]),
                ],
              ),
            ),
            Panel(
              title: 'Privacy & diagnostics',
              child: Column(
                children: [
                  _Toggle(
                    'Send usage telemetry',
                    'Not available — SentinelAI is local-first and never sends data anywhere.',
                    value: false,
                  ),
                  _Toggle(
                    'Auto-load last experiment',
                    'Reopen the run you were looking at when the app starts.',
                    value: s.autoLoadLast,
                    onChanged: (v) => _update((x) => x.copyWith(autoLoadLast: v)),
                  ),
                  _Toggle(
                    'Keep decision audit log',
                    'Always on: every alert triage change is stored with who and when.',
                    value: true,
                  ),
                  _Toggle(
                    'Show demo data labels',
                    'Always on: required by the research-integrity rules so DEMO results are never mistaken for real ones.',
                    value: true,
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }

  static Map<String, String> asPaths(Object? v) =>
      v is Map ? {for (final e in v.entries) '${e.key}': '${e.value}'} : const {};
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.child);
  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Row(
      children: [
        Expanded(child: Text(label, style: const TextStyle(fontSize: 13.5))),
        child,
      ],
    ),
  );
}

class _ReadOnly extends StatelessWidget {
  const _ReadOnly(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: 260,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    decoration: BoxDecoration(
      color: AppColors.isGlass ? const Color(0x40FFFFFF) : AppColors.panelRaised.withValues(alpha: 0.5),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
    ),
    child: Text(
      text,
      overflow: TextOverflow.ellipsis,
      style: TextStyle(color: AppColors.textSecondary, fontSize: 12.5),
    ),
  );
}

class _PathField extends StatelessWidget {
  const _PathField({required this.label, required this.path});
  final String label;
  final String? path;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
        const SizedBox(height: 6),
        Container(
          padding: const EdgeInsets.only(left: 12),
          decoration: BoxDecoration(
            color: AppColors.isGlass ? const Color(0x40FFFFFF) : AppColors.panelRaised.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
          ),
          child: Row(
            children: [
              Expanded(
                child: SelectableText(
                  path ?? '—',
                  maxLines: 1,
                  style: TextStyle(color: AppColors.textSecondary, fontSize: 12.5),
                ),
              ),
              IconButton(
                tooltip: 'Copy path',
                iconSize: 16,
                onPressed: path == null
                    ? null
                    : () async {
                        await Clipboard.setData(ClipboardData(text: path!));
                        if (context.mounted) showSnack(context, 'Copied $label path');
                      },
                icon: Icon(Icons.content_copy_rounded, color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _Toggle extends StatelessWidget {
  const _Toggle(this.label, this.help, {required this.value, this.onChanged});
  final String label;
  final String help;
  final bool value;
  final ValueChanged<bool>? onChanged; // null = locked by policy

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 9),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(label, style: const TextStyle(fontSize: 13.5)),
                  if (onChanged == null) ...[
                    const SizedBox(width: 8),
                    Icon(Icons.lock_outline, size: 13, color: AppColors.textMuted),
                  ],
                ],
              ),
              const SizedBox(height: 3),
              Text(help, style: TextStyles.secondary),
            ],
          ),
        ),
        const SizedBox(width: 16),
        // Locked switches keep their colour (green on / grey off) so the state stays readable.
        IgnorePointer(
          ignoring: onChanged == null,
          child: Opacity(
            opacity: onChanged == null ? 0.65 : 1,
            child: Switch(
              value: value,
              onChanged: onChanged ?? (_) {},
              trackColor: onChanged == null && !value ? WidgetStatePropertyAll(AppColors.track) : null,
            ),
          ),
        ),
      ],
    ),
  );
}
