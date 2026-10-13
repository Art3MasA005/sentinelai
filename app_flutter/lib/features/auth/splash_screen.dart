import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth.dart';
import '../../core/brand.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

/// First screen: brand animation + boot sequence (backend → sign-in options → saved session).
/// The mark drops in, jumps, lands, then rolls left; the name is revealed from behind it as it goes.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  /// Length of the brand animation; the boot sequence keeps the splash up at least this long.
  static const intro = Duration(milliseconds: 2600);

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _intro = AnimationController(vsync: this, duration: SplashScreen.intro);

  static const _steps = {'Connecting to local backend…': 1, 'Loading sign-in options…': 2, 'Checking your session…': 3};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(authProvider.notifier).boot();
      if (!mounted) return;
      // Respect the OS "reduce motion" setting: show the final frame at once.
      if (MediaQuery.of(context).disableAnimations) {
        _intro.value = 1;
      } else {
        _intro.forward();
      }
    });
  }

  @override
  void dispose() {
    _intro.dispose();
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
    // Late elements of the sequence: tagline, then status and footer.
    final tagline = CurvedAnimation(parent: _intro, curve: const Interval(0.80, 0.96, curve: Curves.easeOutCubic));
    final status = CurvedAnimation(parent: _intro, curve: const Interval(0.88, 1.0, curve: Curves.easeOut));
    return Scaffold(
      backgroundColor: bg,
      body: Stack(
        children: [
          Center(
            child: SizedBox(
              width: 360,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _BrandIntro(animation: _intro),
                  const SizedBox(height: 10),
                  FadeTransition(
                    opacity: tagline,
                    child: SlideTransition(
                      position: Tween(begin: const Offset(0, 0.6), end: Offset.zero).animate(tagline),
                      child: Text(
                        'Intrusion detection research console',
                        style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
                      ),
                    ),
                  ),
                  const SizedBox(height: 40),
                  // Offline help must stay reachable even if the backend fails before the intro ends.
                  FadeTransition(
                    opacity: offline ? const AlwaysStoppedAnimation(1.0) : status,
                    child: SizedBox(
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
                  ),
                ],
              ),
            ),
          ),
          Positioned(
            left: 28,
            right: 28,
            bottom: 22,
            child: FadeTransition(
              opacity: status,
              child: DefaultTextStyle(
                style: TextStyle(fontSize: 11, color: AppColors.textMuted),
                child: const Row(children: [Text('v0.1.0'), Spacer(), Text('Local  ·  Offline replay')]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The brand sequence, driven by one controller (0 → 1):
///   0.00–0.12  the mark drops in (scale and fade)
///   0.12–0.55  it crouches, jumps, lands with a squash and settles, with a ground shadow
///   0.55–0.86  it rolls left by one full turn to its final place; the name is revealed from
///              the spot it leaves, behind its trailing edge
/// Final layout: mark and name side by side, centred as a group.
class _BrandIntro extends StatelessWidget {
  const _BrandIntro({required this.animation});
  final Animation<double> animation;

  static const double _mark = 40;
  static const double _gap = 14;
  static const double _jump = 46;

  static double _seg(double t, double a, double b, [Curve curve = Curves.linear]) =>
      curve.transform(((t - a) / (b - a)).clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) {
    final nameStyle = TextStyle(fontSize: 30, fontWeight: FontWeight.w600, letterSpacing: -0.8, color: AppColors.text);
    final painter = TextPainter(
      text: TextSpan(text: 'SentinelAI', style: nameStyle),
      textDirection: TextDirection.ltr,
      textScaler: MediaQuery.textScalerOf(context),
    )..layout();
    final textW = painter.width, textH = painter.height;
    final width = _mark + _gap + textW;
    final travel = (_gap + textW) / 2; // mark starts at the group's centre, ends at its left edge
    const height = _mark + _jump + 12;
    final groundY = height - 12; // bottom of the mark when it rests

    return AnimatedBuilder(
      animation: animation,
      builder: (context, _) {
        final t = animation.value;

        // Drop in.
        final enter = _seg(t, 0.0, 0.12, Curves.easeOutBack);
        final opacity = _seg(t, 0.0, 0.08);

        // Jump: crouch, rise, fall, land squash, settle.
        final crouch = _seg(t, 0.12, 0.18, Curves.easeOut) - _seg(t, 0.18, 0.22, Curves.easeOut);
        final up = _seg(t, 0.18, 0.32, Curves.easeOutCubic);
        final down = _seg(t, 0.32, 0.44, Curves.easeInCubic);
        final lift = _jump * (up - down);
        final land = _seg(t, 0.44, 0.48, Curves.easeOut) - _seg(t, 0.48, 0.55, Curves.easeOutBack);
        final airborne = t > 0.18 && t < 0.44;
        final stretch = airborne ? 0.08 * math.sin(math.pi * _seg(t, 0.18, 0.44)) : 0.0;
        final squash = 0.14 * crouch + 0.18 * land;
        final scaleY = (1 - squash + stretch) * enter;
        final scaleX = (1 + squash - stretch * 0.6) * enter;

        // Roll: translate left by `travel` and turn one full counter-clockwise revolution.
        final roll = _seg(t, 0.55, 0.86, Curves.easeInOutCubic);
        final markLeft = travel * (1 - roll);
        final angle = -2 * math.pi * roll;

        // Name window: opens from the spot the mark left, behind its trailing (right) edge. The soft
        // edges sit outside the text once the roll is done, so the final name is fully opaque.
        const feather = 18.0;
        final revealLeft = markLeft + _mark + _gap * 0.5 - feather;
        final revealRight = revealLeft + 2 * travel * roll + 2 * feather * roll;
        final textLeft = _mark + _gap;

        // Ground shadow only while the jump is under way; at rest it would read as a fourth bar of the mark.
        final shadowScale = 1 - 0.55 * (lift / _jump);
        final shadowAlpha = 0.28 * math.sin(math.pi * _seg(t, 0.12, 0.55));
        return SizedBox(
          width: width,
          height: height,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              // Name, masked to the revealed window with soft edges.
              Positioned(
                left: textLeft,
                top: groundY - _mark / 2 - textH / 2,
                child: ShaderMask(
                  blendMode: BlendMode.dstIn,
                  shaderCallback: (rect) {
                    // Positions relative to the text box; stops must be ascending even for a narrow window.
                    final l = (revealLeft - textLeft) / rect.width;
                    final r = (revealRight - textLeft) / rect.width;
                    final mid = (l + r) / 2;
                    final f = feather / rect.width;
                    double s(double v) => v.clamp(0.0, 1.0);
                    return LinearGradient(
                      colors: const [Colors.transparent, Colors.white, Colors.white, Colors.transparent],
                      stops: [s(l), s(math.min(l + f, mid)), s(math.max(r - f, mid)), s(r)],
                    ).createShader(rect);
                  },
                  child: Text('SentinelAI', style: nameStyle),
                ),
              ),
              // Ground shadow under the mark.
              Positioned(
                left: markLeft,
                top: groundY + 3,
                child: Opacity(
                  opacity: (shadowAlpha * shadowScale).clamp(0.0, 1.0),
                  child: Transform.scale(
                    scaleX: shadowScale,
                    child: Container(
                      width: _mark,
                      height: 4,
                      decoration: BoxDecoration(
                        color: AppColors.textMuted,
                        borderRadius: BorderRadius.circular(2),
                        boxShadow: [BoxShadow(color: AppColors.textMuted, blurRadius: 8)],
                      ),
                    ),
                  ),
                ),
              ),
              // The mark: squash/stretch from its base, rotation about its centre.
              Positioned(
                left: markLeft,
                top: groundY - _mark - lift,
                child: Opacity(
                  opacity: opacity,
                  child: Transform(
                    alignment: Alignment.bottomCenter,
                    transform: Matrix4.diagonal3Values(scaleX, scaleY, 1),
                    child: Transform.rotate(angle: angle, child: const SentinelMark(size: _mark)),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
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
