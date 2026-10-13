import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'theme.dart';

/// Frosted-glass toast, floating at the bottom centre: icon in a tinted circle, title and message, a
/// close button and a thin bar that shows the time left. Hovering pauses the timer; a new toast
/// replaces the current one.
///
/// It fades by easing its colours and blur rather than with an opacity layer: inside an opacity layer a
/// BackdropFilter blurs an empty buffer and the glass flashes dark while it appears.
void showToast(BuildContext context, String message, {bool error = false}) {
  final overlay = Overlay.maybeOf(context, rootOverlay: true);
  if (overlay == null) return;
  _current?.dismiss();
  late final OverlayEntry entry;
  final key = GlobalKey<_ToastState>();
  entry = OverlayEntry(
    builder: (_) => _Toast(
      key: key,
      message: message,
      error: error,
      onGone: () {
        if (entry.mounted) entry.remove();
        if (_current?.key == key) _current = null;
      },
    ),
  );
  _current = _Handle(key);
  overlay.insert(entry);
}

_Handle? _current;

class _Handle {
  _Handle(this.key);
  final GlobalKey<_ToastState> key;
  void dismiss() => key.currentState?.dismiss();
}

class _Toast extends StatefulWidget {
  const _Toast({super.key, required this.message, required this.error, required this.onGone});
  final String message;
  final bool error;
  final VoidCallback onGone;

  @override
  State<_Toast> createState() => _ToastState();
}

class _ToastState extends State<_Toast> with TickerProviderStateMixin {
  late final AnimationController _show = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 340),
    reverseDuration: const Duration(milliseconds: 220),
  );
  late final AnimationController _life = AnimationController(
    vsync: this,
    duration: Duration(milliseconds: widget.error ? 6000 : 3600),
  );
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    _show.forward();
    _life.forward();
    _life.addStatusListener((s) {
      if (s == AnimationStatus.completed) dismiss();
    });
  }

  void dismiss() {
    if (_leaving || !mounted) return;
    _leaving = true;
    _life.stop();
    _show.reverse().whenComplete(widget.onGone);
  }

  @override
  void dispose() {
    _show.dispose();
    _life.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final glass = AppColors.isGlass;
    final accent = widget.error ? AppColors.red : AppColors.green;
    final width = MediaQuery.sizeOf(context).width;
    return Positioned(
      left: 0,
      right: 0,
      bottom: 28 + MediaQuery.paddingOf(context).bottom,
      // Overlay entries sit outside any Material, which leaves text unstyled (yellow underlines).
      child: Material(
        type: MaterialType.transparency,
        child: Center(
          child: AnimatedBuilder(
            animation: Listenable.merge([_show, _life]),
            builder: (context, _) {
              final a = Curves.easeOutCubic.transform(_show.value);
              Color fade(Color c) => c.withValues(alpha: c.a * a);
              final surface = glass ? const Color(0xB8FFFFFF) : const Color(0xC70F1826);
              final edge = glass ? const Color(0xCCFFFFFF) : const Color(0x24FFFFFF);
              final ink = glass ? const Color(0xFF0F172A) : const Color(0xFFE8EEF8);
              final muted = glass ? const Color(0xFF526077) : const Color(0xFF93A1B5);
              return Transform.translate(
                offset: Offset(0, 22 * (1 - a)),
                child: Transform.scale(
                  scale: 0.96 + 0.04 * a,
                  child: MouseRegion(
                    onEnter: (_) => _life.stop(),
                    onExit: (_) {
                      if (!_leaving) _life.forward();
                    },
                    child: GestureDetector(
                      onTap: dismiss,
                      child: Container(
                        width: (width - 48).clamp(260.0, 460.0),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(16),
                          boxShadow: [
                            BoxShadow(
                              color: fade(glass ? const Color(0x261E293B) : const Color(0x66000000)),
                              blurRadius: 32,
                              offset: const Offset(0, 14),
                            ),
                          ],
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(16),
                          child: BackdropFilter(
                            filter: ImageFilter.blur(sigmaX: 22 * a + 0.01, sigmaY: 22 * a + 0.01),
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: fade(surface),
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(color: fade(edge)),
                              ),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Padding(
                                    padding: const EdgeInsets.fromLTRB(14, 12, 6, 10),
                                    child: Row(
                                      children: [
                                        Container(
                                          width: 32,
                                          height: 32,
                                          decoration: BoxDecoration(
                                            shape: BoxShape.circle,
                                            color: fade(accent.withValues(alpha: 0.16)),
                                          ),
                                          child: Icon(
                                            widget.error ? Icons.priority_high_rounded : Icons.check_rounded,
                                            size: 18,
                                            color: fade(accent),
                                          ),
                                        ),
                                        const SizedBox(width: 12),
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment: CrossAxisAlignment.start,
                                            mainAxisSize: MainAxisSize.min,
                                            children: [
                                              Text(
                                                widget.error ? 'Something went wrong' : 'Done',
                                                style: TextStyle(
                                                  fontSize: 12,
                                                  fontWeight: FontWeight.w600,
                                                  color: fade(muted),
                                                ),
                                              ),
                                              const SizedBox(height: 2),
                                              Text(
                                                widget.message,
                                                maxLines: 3,
                                                overflow: TextOverflow.ellipsis,
                                                style: TextStyle(fontSize: 13.5, height: 1.3, color: fade(ink)),
                                              ),
                                            ],
                                          ),
                                        ),
                                        IconButton(
                                          tooltip: 'Dismiss',
                                          visualDensity: VisualDensity.compact,
                                          onPressed: dismiss,
                                          icon: Icon(Icons.close_rounded, size: 17, color: fade(muted)),
                                        ),
                                      ],
                                    ),
                                  ),
                                  // Time left.
                                  Align(
                                    alignment: Alignment.centerLeft,
                                    child: FractionallySizedBox(
                                      widthFactor: 1 - _life.value,
                                      child: Container(height: 2.5, color: fade(accent.withValues(alpha: 0.75))),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}
