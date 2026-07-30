import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/main.dart';

void main() {
  testWidgets('1024x600 横屏界面快照', (tester) async {
    final latinFont = FontLoader('PuzzleLatin')
      ..addFont(rootBundle.load('assets/fonts/DejaVuSans.ttf'));
    final chineseFont = FontLoader('PuzzleChinese')
      ..addFont(rootBundle.load('assets/fonts/DroidSansFallbackFull.ttf'));
    await latinFont.load();
    await chineseFont.load();

    await tester.binding.setSurfaceSize(const Size(1024, 600));
    await tester.pumpWidget(const PuzzleStudioApp());
    await tester.pumpAndSettle();

    await expectLater(
      find.byType(PuzzleDashboard),
      matchesGoldenFile('goldens/dashboard_1024x600.png'),
    );

    await tester.binding.setSurfaceSize(null);
  });
}
