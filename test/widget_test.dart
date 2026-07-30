import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/main.dart';

void main() {
  testWidgets('横屏控制台包含三个模式和真实结果区', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1024, 600));
    await tester.pumpWidget(const PuzzleStudioApp());

    expect(find.text('第一问'), findsOneWidget);
    expect(find.text('普通拼图'), findsOneWidget);
    expect(find.text('扑克牌'), findsAtLeast(1));
    expect(find.text('扑克牌拼接实图'), findsOneWidget);
    expect(find.text('开始求解'), findsOneWidget);

    await tester.binding.setSurfaceSize(null);
  });
}
