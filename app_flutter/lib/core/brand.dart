import 'package:flutter/material.dart';

import 'theme.dart';

/// Brand mark: three replay windows, the middle one shifted — drift. The same drawing is used for the
/// splash, the sidebar and the app icons (see tool/make_icons.py).
class SentinelMark extends StatelessWidget {
  const SentinelMark({super.key, this.size = 32, this.ink, this.accent});
  final double size;
  final Color? ink;
  final Color? accent;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: size,
    height: size,
    child: CustomPaint(
      painter: _MarkPainter(ink: ink ?? AppColors.text, accent: accent ?? AppColors.blue),
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

/// Mark and name side by side, as at the end of the splash animation.
class SentinelWordmark extends StatelessWidget {
  const SentinelWordmark({super.key, this.markSize = 22, this.fontSize = 18});
  final double markSize;
  final double fontSize;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      SentinelMark(size: markSize),
      SizedBox(width: markSize * 0.42),
      Text(
        'SentinelAI',
        style: TextStyle(fontSize: fontSize, fontWeight: FontWeight.w600, letterSpacing: -0.4, color: AppColors.text),
      ),
    ],
  );
}
