import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/main.dart';

void main() {
  testWidgets('横屏控制台包含拼图、机械臂和设置页面', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(const PuzzleStudioApp());

    expect(find.text('第一问'), findsOneWidget);
    expect(find.text('普通拼图'), findsOneWidget);
    expect(find.text('扑克牌'), findsAtLeast(1));
    expect(find.text('扑克牌拼接实图'), findsOneWidget);
    expect(find.text('开始求解'), findsOneWidget);

    await tester.tap(find.text('机械臂'));
    await tester.pump();

    expect(find.text('机械臂手动控制'), findsOneWidget);
    expect(find.text('移动到绝对位置'), findsOneWidget);
    expect(find.text('按输入量相对移动'), findsOneWidget);
    expect(find.text('归零'), findsOneWidget);

    await tester.tap(find.text('设置').first);
    await tester.pump();

    expect(find.text('二值化实时预览'), findsOneWidget);
    expect(find.text('背景颜色'), findsOneWidget);
    expect(find.text('黑色'), findsOneWidget);
    expect(find.text('绿色'), findsOneWidget);
    expect(find.text('自动 OTSU'), findsOneWidget);
    expect(find.text('自动'), findsOneWidget);
    expect(find.text('亮色'), findsOneWidget);
    expect(find.text('暗色'), findsOneWidget);
    expect(find.text('最小碎片面积'), findsOneWidget);

    await tester.tap(find.text('串口设置'));
    await tester.pump();

    expect(find.text('串口设备'), findsOneWidget);
    expect(find.text('波特率'), findsOneWidget);
    expect(find.text('自动抓取Z'), findsOneWidget);
    expect(find.text('自动放置Z'), findsOneWidget);
    expect(find.text('保存并连接'), findsOneWidget);

    await tester.binding.setSurfaceSize(null);
  });
}
