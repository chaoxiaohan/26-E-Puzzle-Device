import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/backend_bridge.dart';

void main() {
  test('视觉调参字段完整写入控制文件', () async {
    final path =
        '${Directory.systemTemp.path}/puzzle_tuning_${DateTime.now().microsecondsSinceEpoch}.json';
    final file = File(path);
    addTearDown(() async {
      if (await file.exists()) {
        await file.delete();
      }
    });

    final bridge = BackendBridge(controlPath: path);
    await bridge.sendControl(
      autoThreshold: false,
      manualThreshold: 173,
      polarityMode: 'DARK',
      backgroundMode: 'GREEN',
      minPieceArea: 2345,
    );

    final payload = jsonDecode(await file.readAsString());
    expect(payload['auto_threshold'], isFalse);
    expect(payload['manual_threshold'], 173);
    expect(payload['polarity_mode'], 'DARK');
    expect(payload['background_mode'], 'GREEN');
    expect(payload['min_piece_area'], 2345);
    expect(payload['revision'], isA<int>());
  });
}
