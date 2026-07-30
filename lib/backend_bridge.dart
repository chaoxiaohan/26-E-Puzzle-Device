import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

class BackendSnapshot {
  const BackendSnapshot({
    required this.backendAlive,
    required this.cameraOk,
    required this.mode,
    required this.fps,
    required this.pieceCount,
    required this.autoThreshold,
    required this.manualThreshold,
    required this.currentThreshold,
    required this.polarityMode,
    required this.backgroundMode,
    required this.minPieceArea,
    required this.solving,
    required this.solverMessage,
    required this.score,
    required this.ratio,
    required this.solverMs,
    required this.resultAvailable,
    required this.frameRevision,
    required this.resultRevision,
    required this.lastCaptureName,
    required this.motionPlanCount,
    required this.serialConnected,
    required this.serialPort,
    required this.serialBaud,
    required this.serialPickZ,
    required this.serialPlaceZ,
    required this.serialLastReply,
    required this.serialError,
  });

  factory BackendSnapshot.fromJson(Map<String, dynamic> json) {
    return BackendSnapshot(
      backendAlive: json['backend_alive'] == true,
      cameraOk: json['camera_ok'] == true,
      mode: json['mode']?.toString() ?? 'card',
      fps: (json['fps'] as num?)?.toDouble() ?? 0,
      pieceCount: (json['piece_count'] as num?)?.toInt() ?? 0,
      autoThreshold: json['auto_threshold'] != false,
      manualThreshold: (json['manual_threshold'] as num?)?.toInt() ?? 128,
      currentThreshold: (json['current_threshold'] as num?)?.toInt() ?? 128,
      polarityMode: json['polarity_mode']?.toString() ?? 'AUTO',
      backgroundMode: json['background_mode']?.toString() ?? 'BLACK',
      minPieceArea: (json['min_piece_area'] as num?)?.toInt() ?? 1500,
      solving: json['solving'] == true,
      solverMessage: json['solver_message']?.toString() ?? '',
      score: (json['score'] as num?)?.toDouble() ?? 0,
      ratio: (json['ratio'] as num?)?.toDouble() ?? 0,
      solverMs: (json['solver_ms'] as num?)?.toDouble() ?? 0,
      resultAvailable: json['result_available'] == true,
      frameRevision: (json['frame_revision'] as num?)?.toInt() ?? 0,
      resultRevision: (json['result_revision'] as num?)?.toInt() ?? 0,
      lastCaptureName: json['last_capture_name']?.toString() ?? '',
      motionPlanCount: (json['motion_plan_count'] as num?)?.toInt() ?? 0,
      serialConnected: json['serial_connected'] == true,
      serialPort: json['serial_port']?.toString() ?? '/dev/serial0',
      serialBaud: (json['serial_baud'] as num?)?.toInt() ?? 115200,
      serialPickZ: (json['serial_pick_z'] as num?)?.toInt() ?? 0,
      serialPlaceZ: (json['serial_place_z'] as num?)?.toInt() ?? 0,
      serialLastReply: json['serial_last_reply']?.toString() ?? '',
      serialError: json['serial_error']?.toString() ?? '',
    );
  }

  final bool backendAlive;
  final bool cameraOk;
  final String mode;
  final double fps;
  final int pieceCount;
  final bool autoThreshold;
  final int manualThreshold;
  final int currentThreshold;
  final String polarityMode;
  final String backgroundMode;
  final int minPieceArea;
  final bool solving;
  final String solverMessage;
  final double score;
  final double ratio;
  final double solverMs;
  final bool resultAvailable;
  final int frameRevision;
  final int resultRevision;
  final String lastCaptureName;
  final int motionPlanCount;
  final bool serialConnected;
  final String serialPort;
  final int serialBaud;
  final int serialPickZ;
  final int serialPlaceZ;
  final String serialLastReply;
  final String serialError;
}

class BackendUpdate {
  const BackendUpdate({
    required this.snapshot,
    this.frame,
    this.binary,
    this.result,
    this.clearResult = false,
  });

  final BackendSnapshot snapshot;
  final Uint8List? frame;
  final Uint8List? binary;
  final Uint8List? result;
  final bool clearResult;
}

class BackendBridge {
  final File _control = File('/tmp/puzzle_ui_control.json');
  final File _state = File('/tmp/puzzle_ui_state.json');
  final File _frame = File('/tmp/puzzle_ui_frame.jpg');
  final File _binary = File('/tmp/puzzle_ui_binary.jpg');
  final File _result = File('/tmp/puzzle_ui_result.jpg');
  int _frameRevision = -1;
  int _resultRevision = -1;
  Uint8List? _cachedResult;

  Future<BackendUpdate?> poll() async {
    try {
      final json = jsonDecode(await _state.readAsString());
      if (json is! Map<String, dynamic>) {
        return null;
      }
      final updatedAt = (json['updated_at_ms'] as num?)?.toInt() ?? 0;
      if (DateTime.now().millisecondsSinceEpoch - updatedAt > 1800) {
        return null;
      }

      final snapshot = BackendSnapshot.fromJson(json);
      Uint8List? frame;
      Uint8List? binary;
      Uint8List? result;
      var clearResult = false;

      if (snapshot.frameRevision != _frameRevision) {
        frame = await _frame.readAsBytes();
        binary = await _binary.readAsBytes();
        _frameRevision = snapshot.frameRevision;
      }
      if (snapshot.resultRevision != _resultRevision) {
        if (snapshot.resultAvailable && await _result.exists()) {
          _cachedResult = await _result.readAsBytes();
          result = _cachedResult;
        } else {
          _cachedResult = null;
          clearResult = true;
        }
        _resultRevision = snapshot.resultRevision;
      } else if (snapshot.resultAvailable) {
        result = _cachedResult;
      }
      return BackendUpdate(
        snapshot: snapshot,
        frame: frame,
        binary: binary,
        result: result,
        clearResult: clearResult,
      );
    } on FileSystemException {
      return null;
    } on FormatException {
      return null;
    }
  }

  Future<void> sendControl({
    String? mode,
    String? action,
    bool? autoThreshold,
    int? manualThreshold,
    String? polarityMode,
    String? backgroundMode,
    int? minPieceArea,
    String? serialPort,
    int? serialBaud,
    int? serialPickZ,
    int? serialPlaceZ,
    int? armX,
    int? armY,
    int? armZ,
    int? armRotationCdeg,
  }) async {
    final payload = <String, Object>{
      'revision': DateTime.now().microsecondsSinceEpoch,
    };
    if (mode != null) {
      payload['mode'] = mode;
    }
    if (action != null) {
      payload['action'] = action;
    }
    if (autoThreshold != null) {
      payload['auto_threshold'] = autoThreshold;
    }
    if (manualThreshold != null) {
      payload['manual_threshold'] = manualThreshold;
    }
    if (polarityMode != null) {
      payload['polarity_mode'] = polarityMode;
    }
    if (backgroundMode != null) {
      payload['background_mode'] = backgroundMode;
    }
    if (minPieceArea != null) {
      payload['min_piece_area'] = minPieceArea;
    }
    if (serialPort != null) {
      payload['serial_port'] = serialPort;
    }
    if (serialBaud != null) {
      payload['serial_baud'] = serialBaud;
    }
    if (serialPickZ != null) {
      payload['serial_pick_z'] = serialPickZ;
    }
    if (serialPlaceZ != null) {
      payload['serial_place_z'] = serialPlaceZ;
    }
    if (armX != null) {
      payload['arm_x'] = armX;
    }
    if (armY != null) {
      payload['arm_y'] = armY;
    }
    if (armZ != null) {
      payload['arm_z'] = armZ;
    }
    if (armRotationCdeg != null) {
      payload['arm_rotation_cdeg'] = armRotationCdeg;
    }

    final temporary = File('${_control.path}.$pid.tmp');
    await temporary.writeAsString(jsonEncode(payload), flush: true);
    await temporary.rename(_control.path);
  }

  Future<String> readBackendLog({int maximumBytes = 24000}) async {
    try {
      final file = File('/tmp/puzzle_backend.log');
      if (!await file.exists()) {
        return '暂无后端日志';
      }
      final bytes = await file.readAsBytes();
      final start = bytes.length > maximumBytes
          ? bytes.length - maximumBytes
          : 0;
      return utf8.decode(bytes.sublist(start), allowMalformed: true);
    } on FileSystemException {
      return '无法读取后端日志';
    }
  }
}
