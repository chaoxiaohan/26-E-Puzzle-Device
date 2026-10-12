import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:puzzle_flutter_ui/backend_bridge.dart';

void main() {
  test('serial reconnect state is parsed', () {
    final snapshot = BackendSnapshot.fromJson({
      'serial_connected': false,
      'serial_port': '/dev/ttyUSB0',
      'serial_active_port': '/dev/ttyUSB1',
      'serial_reconnecting': true,
      'serial_device_present': true,
    });

    expect(snapshot.serialConnected, isFalse);
    expect(snapshot.serialPort, '/dev/ttyUSB0');
    expect(snapshot.serialActivePort, '/dev/ttyUSB1');
    expect(snapshot.serialReconnecting, isTrue);
    expect(snapshot.serialDevicePresent, isTrue);
  });

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
      roiX: 42,
      roiY: 64,
      roiWidth: 500,
      roiHeight: 900,
    );

    final payload = jsonDecode(await file.readAsString());
    expect(payload['auto_threshold'], isFalse);
    expect(payload['manual_threshold'], 173);
    expect(payload['polarity_mode'], 'DARK');
    expect(payload['background_mode'], 'GREEN');
    expect(payload['min_piece_area'], 2345);
    expect(payload['roi_x'], 42);
    expect(payload['roi_y'], 64);
    expect(payload['roi_width'], 500);
    expect(payload['roi_height'], 900);
    expect(payload['revision'], isA<int>());
  });
}
