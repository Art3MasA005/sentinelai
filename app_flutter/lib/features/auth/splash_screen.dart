import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

/// First screen: brand + boot sequence (backend → sign-in options → saved session).
/// Deliberately quiet: flat background, one accent, a short fade.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _fade = AnimationController(vsync: this, duration: const Duration(milliseconds: 450))
    ..forward();

  static const _steps = {'Connecting to local backend…': 1, 'Loading sign-in options…': 2, 'Checking your session…': 3};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(authProvider.notifier).boot());
  }

  @override
  void dispose() {
    _fade.dispose();
    super.dispose();
  }

  Future<void> _changeUrl() async {
    final ctl = TextEditingController(text: ref.read(settingsProvider).baseUrl);
    final url = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        title: const Text('Backend address', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        content: SizedBox(
          width: 360,
          child: TextField(
            controller: ctl,
            autofocus: true,
            style: const TextStyle(fontSize: 13),
            decoration: const InputDecoration(hintText: 'http://127.0.0.1:8765'),
            onSubmitted: (v) => Navigator.pop(context, v),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, ctl.text), child: const Text('Connect')),
        ],
      ),
    );
    ctl.dispose();
    final clean = url?.trim().replaceAll(RegExp(r'/+$'), '');
    if (clean == null || clean.isEmpty) return;
    ref.read(settingsProvider.notifier).update(ref.read(settingsProvider).copyWith(baseUrl: clean));
    ref.read(authProvider.notifier).boot();
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final offline = auth.phase == AuthPhase.offline;
    final url = ref.watch(settingsProvider).baseUrl;
    final bg = AppColors.isGlass ? const Color(0xFFF5F6F8) : AppColors.background;
    return Scaffold(
      backgroundColor: bg,
      body: FadeTransition(
        opacity: CurvedAnimation(parent: _fade, curve: Curves.easeOut),
        child: Stack(
          children: [
            Center(
              child: SizedBox(
                width: 360,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SentinelMark(size: 36),
                    const SizedBox(height: 22),
                    Text(
                      'SentinelAI',
                      style: TextStyle(
                        fontSize: 26,
                        fontWeight: FontWeight.w600,
                        letterSpacing: -0.6,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Intrusion detection research console',
                      style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 40),
                    SizedBox(
                      height: 120, // fixed so switching to the offline message doesn't shift the logo
                      child: offline
                          ? _Offline(
                              url: url,
                              error: auth.error,
                              onRetry: () => ref.read(authProvider.notifier).boot(),
                              onChangeUrl: _changeUrl,
                            )
                          : _Status(step: auth.step, index: _steps[auth.step], progress: auth.progress),
                    ),
                  ],
                ),
              ),
            ),
            Positioned(
              left: 28,
              right: 28,
              bottom: 22,
              child: DefaultTextStyle(
                style: TextStyle(fontSize: 11, color: AppColors.textMuted),
                child: const Row(children: [Text('v0.1.0'), Spacer(), Text('Local  ·  Offline replay')]),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Brand mark: three replay windows, the middle one shifted — drift.
class SentinelMark extends StatelessWidget {
  const SentinelMark({super.key, this.size = 32});
  final double size;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: size,
    height: size,
    child: CustomPaint(
      painter: _MarkPainter(ink: AppColors.text, accent: AppColors.blue),
    ),
  );
}

class _MarkPainter extends CustomPainter {
  _MarkPainter({required this.ink, required this.accent});
  final Color ink;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final bar = h * 0.2, gap = (h - 3 * bar) / 2;
    final r = Radius.circular(bar / 2);
    void draw(double top, double left, double width, Color c) =>
        canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(left, top, width, bar), r), Paint()..color = c);
    draw(0, 0, w * 0.78, ink);
    draw(bar + gap, w * 0.22, w * 0.78, accent);
    draw(2 * (bar + gap), 0, w * 0.6, ink);
  }

  @override
  bool shouldRepaint(_MarkPainter old) => old.ink != ink || old.accent != accent;
}

class _Status extends StatelessWidget {
  const _Status({required this.step, required this.index, required this.progress});
  final String step;
  final int? index;
  final double progress;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      SizedBox(
        width: 200,
        child: TweenAnimationBuilder<double>(
          tween: Tween(end: progress),
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOut,
          builder: (_, v, _) => LinearProgressIndicator(
            value: v,
            minHeight: 1.5,
            backgroundColor: AppColors.border,
            valueColor: AlwaysStoppedAnimation(AppColors.text),
          ),
        ),
      ),
      const SizedBox(height: 12),
      Text(index == null ? step : '$step  $index/3', style: TextStyle(fontSize: 12, color: AppColors.textMuted)),
    ],
  );
}

class _Offline extends StatelessWidget {
  const _Offline({required this.url, required this.error, required this.onRetry, required this.onChangeUrl});
  final String url;
  final String? error;
  final VoidCallback onRetry;
  final VoidCallback onChangeUrl;

  @override
  Widget build(BuildContext context) {
    final outdated = error?.contains('outdated') ?? false;
    final small = OutlinedButton.styleFrom(
      visualDensity: VisualDensity.compact,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      side: BorderSide(color: AppColors.border),
      textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w500),
    );
    return Column(
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: AppColors.red, shape: BoxShape.circle),
            ),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                outdated ? 'Backend needs a restart (outdated version)' : 'Can’t reach the backend at $url',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 13, color: AppColors.text),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        SelectableText(
          outdated ? 'Stop it with Ctrl+C, then: python -m app.cli serve' : 'Start it with: python -m app.cli serve',
          style: TextStyle(fontSize: 12, color: AppColors.textMuted, fontFamily: 'monospace'),
        ),
        const SizedBox(height: 14),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            OutlinedButton(style: small, onPressed: onRetry, child: const Text('Retry')),
            const SizedBox(width: 8),
            OutlinedButton(style: small, onPressed: onChangeUrl, child: const Text('Change address')),
          ],
        ),
      ],
    );
  }
}
