import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import 'theme.dart';

/// Wraps the whole app (MaterialApp.builder) so a dialog can snapshot what is below it.
final appSnapshotKey = GlobalKey(debugLabel: 'app-snapshot');

const _openDuration = Duration(milliseconds: 260);
const _blurSigma = 8.0; // logical pixels

/// The app as it looks now, blurred once. Drawing a ready-made blurred image is cheap, whereas a live
/// full-window BackdropFilter re-blurs every frame of the open/close animation and makes it stutter.
/// Returns null when no snapshot can be taken (the dialog then falls back to a live blur).
ui.Image? _blurredSnapshot(BuildContext context) {
  final boundary = appSnapshotKey.currentContext?.findRenderObject();
  if (boundary is! RenderRepaintBoundary || !boundary.hasSize) return null;
  var pending = false;
  assert(() {
    pending = boundary.debugNeedsPaint; // toImageSync asserts on this in debug builds
    return true;
  }());
  if (pending) return null;
  try {
    // Half resolution is plenty for an image that is blurred anyway, and halves the work.
    final scale = 0.5 * MediaQuery.devicePixelRatioOf(context);
    final sharp = boundary.toImageSync(pixelRatio: scale);
    final recorder = ui.PictureRecorder();
    final sigma = _blurSigma * scale;
    Canvas(recorder).drawImage(
      sharp,
      Offset.zero,
      Paint()..imageFilter = ui.ImageFilter.blur(sigmaX: sigma, sigmaY: sigma, tileMode: TileMode.clamp),
    );
    final blurred = recorder.endRecording().toImageSync(sharp.width, sharp.height);
    sharp.dispose();
    return blurred;
  } catch (_) {
    return null;
  }
}

/// Modal dialog with a frosted backdrop: the page behind is blurred and only faintly tinted (lighter in
/// the light theme, slightly darker in the dark one) instead of being covered by a dark scrim. The
/// dialog rises and scales in. The dialog itself is never faded with an opacity layer, so frosted-glass
/// panels inside it do not flash dark while it opens or closes.
Future<T?> showFrostedDialog<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool barrierDismissible = true,
}) {
  final snapshot = _blurredSnapshot(context);
  final tint = AppColors.isGlass ? const Color(0x29FFFFFF) : const Color(0x33000000);
  final future = showGeneralDialog<T>(
    context: context,
    barrierDismissible: barrierDismissible,
    barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
    barrierColor: Colors.transparent,
    transitionDuration: _openDuration,
    pageBuilder: (context, _, _) => builder(context),
    transitionBuilder: (context, animation, _, child) {
      final c = CurvedAnimation(parent: animation, curve: Curves.easeOutCubic, reverseCurve: Curves.easeInCubic);
      final Widget backdrop = snapshot != null
          // Cheap path: fade in the pre-blurred snapshot (no backdrop filter inside the fading layer).
          ? FadeTransition(
              opacity: c,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  RawImage(image: snapshot, fit: BoxFit.fill, filterQuality: FilterQuality.medium),
                  ColoredBox(color: tint),
                ],
              ),
            )
          // Fallback: live blur whose strength follows the animation.
          : AnimatedBuilder(
              animation: c,
              builder: (_, _) => BackdropFilter(
                filter: ui.ImageFilter.blur(sigmaX: _blurSigma * c.value + 0.01, sigmaY: _blurSigma * c.value + 0.01),
                child: ColoredBox(color: tint.withValues(alpha: tint.a * c.value)),
              ),
            );
      return Stack(
        fit: StackFit.expand,
        children: [
          // Taps fall through to the route's (transparent) barrier, which dismisses the dialog.
          IgnorePointer(child: RepaintBoundary(child: backdrop)),
          SlideTransition(
            position: Tween(begin: const Offset(0, 0.03), end: Offset.zero).animate(c),
            child: ScaleTransition(scale: Tween(begin: 0.97, end: 1.0).animate(c), child: child),
          ),
        ],
      );
    },
  );
  // The future completes when the dialog is popped, while its closing animation still draws the image.
  if (snapshot != null) {
    unawaited(future.whenComplete(() => Future<void>.delayed(_openDuration * 2, snapshot.dispose)));
  }
  return future;
}

/// Compact confirmation dialog: tinted icon, title, message, Cancel and a confirm button (red when the
/// action is destructive). Returns true when confirmed.
Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  String confirmLabel = 'Confirm',
  bool destructive = false,
  IconData? icon,
}) async {
  final ok = await showFrostedDialog<bool>(
    context: context,
    builder: (context) => _ConfirmDialog(
      title: title,
      message: message,
      confirmLabel: confirmLabel,
      destructive: destructive,
      icon: icon ?? (destructive ? Icons.delete_outline_rounded : Icons.help_outline_rounded),
    ),
  );
  return ok == true;
}

class _ConfirmDialog extends StatelessWidget {
  const _ConfirmDialog({
    required this.title,
    required this.message,
    required this.confirmLabel,
    required this.destructive,
    required this.icon,
  });
  final String title, message, confirmLabel;
  final bool destructive;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final accent = destructive ? AppColors.red : AppColors.blue;
    return Center(
      child: Material(
        type: MaterialType.transparency,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Glass(
              radius: 20,
              blur: 30,
              color: AppColors.isGlass ? const Color(0xEBFFFFFF) : AppColors.panelRaised,
              padding: const EdgeInsets.fromLTRB(22, 22, 22, 18),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 40,
                        height: 40,
                        decoration: BoxDecoration(shape: BoxShape.circle, color: accent.withValues(alpha: 0.13)),
                        child: Icon(icon, size: 21, color: accent),
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const SizedBox(height: 2),
                            Text(
                              title,
                              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
                            ),
                            const SizedBox(height: 6),
                            Text(message, style: TextStyle(fontSize: 13, height: 1.45, color: AppColors.textSecondary)),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      OutlinedButton(
                        onPressed: () => Navigator.pop(context, false),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                          side: BorderSide(color: AppColors.border),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        child: Text('Cancel', style: TextStyle(color: AppColors.text)),
                      ),
                      const SizedBox(width: 10),
                      FilledButton(
                        // Enter confirms only harmless actions; a destructive one needs a deliberate click.
                        autofocus: !destructive,
                        onPressed: () => Navigator.pop(context, true),
                        style: FilledButton.styleFrom(
                          backgroundColor: accent,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        child: Text(confirmLabel, style: const TextStyle(fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
