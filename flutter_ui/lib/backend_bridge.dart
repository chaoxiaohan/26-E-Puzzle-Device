import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

List<double>? _pointFromJson(Object? value) {
  if (value is! List || value.length < 2) {
    return null;
  }
  final x = value[0];
  final y = value[1];
  if (x is! num || y is! num) {
    return null;
  }
  return [x.toDouble(), y.toDouble()];
}

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
    required this.greenMethod,
    required this.greenHueMin,
    required this.greenHueMax,
    required this.greenSatMin,
    required this.greenValMin,
    required this.greenCloseKernel,
    required this.greenCloseIter,
    required this.paperCloseKernel,
    required this.paperCloseIter,
    required this.minPieceArea,
    required this.cameraWidth,
    required this.cameraHeight,
    required this.roiX,
    required this.roiY,
    required this.roiWidth,
    required this.roiHeight,
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
    required this.serialActivePort,
    required this.serialReconnecting,
    required this.serialDevicePresent,
    required this.serialBaud,
    required this.serialPickZ,
    required this.serialPlaceZ,
    required this.serialLastReply,
    required this.serialError,
    required this.serialRawLog,
    required this.serialEventRevision,
    required this.platformX,
    required this.platformY,
    required this.platformZ,
    required this.platformRotation,
    required this.platformPositionValid,
    required this.calibrationVisualA,
    required this.calibrationVisualB,
    required this.calibrationVisualC,
    required this.calibrationVisualD,
    required this.calibrationVisualE,
    required this.calibrationVisualF,
    required this.calibrationPlatformA,
    required this.calibrationPlatformB,
    required this.calibrationPlatformC,
    required this.calibrationPlatformD,
    required this.calibrationPlatformE,
    required this.calibrationPlatformF,
    required this.calibrationValid,
    required this.calibrationScaleX,
    required this.calibrationScaleY,
    required this.calibrationAffineDeterminant,
    required this.calibrationRmsError,
    required this.calibrationMaxError,
    required this.assemblySplitY,
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
      backgroundMode: json['background_mode']?.toString() ?? 'GREEN',
      greenMethod: json['green_method']?.toString() ?? 'border',
      greenHueMin: (json['green_hue_min'] as num?)?.toInt() ?? 30,
      greenHueMax: (json['green_hue_max'] as num?)?.toInt() ?? 95,
      greenSatMin: (json['green_sat_min'] as num?)?.toInt() ?? 20,
      greenValMin: (json['green_val_min'] as num?)?.toInt() ?? 6,
      greenCloseKernel: (json['green_close_kernel'] as num?)?.toInt() ?? 7,
      greenCloseIter: (json['green_close_iter'] as num?)?.toInt() ?? 2,
      paperCloseKernel: (json['paper_close_kernel'] as num?)?.toInt() ?? 5,
      paperCloseIter: (json['paper_close_iter'] as num?)?.toInt() ?? 1,
      minPieceArea: (json['min_piece_area'] as num?)?.toInt() ?? 1500,
      cameraWidth: (json['camera_width'] as num?)?.toInt() ?? 720,
      cameraHeight: (json['camera_height'] as num?)?.toInt() ?? 1280,
      roiX: (json['roi_x'] as num?)?.toInt() ?? 10,
      roiY: (json['roi_y'] as num?)?.toInt() ?? 100,
      roiWidth: (json['roi_width'] as num?)?.toInt() ?? 700,
      roiHeight: (json['roi_height'] as num?)?.toInt() ?? 900,
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
      serialPort: json['serial_port']?.toString() ?? '/dev/ttyUSB0',
      serialActivePort: json['serial_active_port']?.toString() ?? '',
      serialReconnecting: json['serial_reconnecting'] == true,
      serialDevicePresent: json['serial_device_present'] == true,
      serialBaud: (json['serial_baud'] as num?)?.toInt() ?? 115200,
      serialPickZ: (json['serial_pick_z'] as num?)?.toInt() ?? 0,
      serialPlaceZ: (json['serial_place_z'] as num?)?.toInt() ?? 0,
      serialLastReply: json['serial_last_reply']?.toString() ?? '',
      serialError: json['serial_error']?.toString() ?? '',
      serialRawLog: (json['serial_raw_log'] as List<dynamic>?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ??
          [],
      serialEventRevision:
          (json['serial_event_revision'] as num?)?.toInt() ?? 0,
      platformX: (json['platform_x'] as num?)?.toInt() ?? 0,
      platformY: (json['platform_y'] as num?)?.toInt() ?? 0,
      platformZ: (json['platform_z'] as num?)?.toInt() ?? 0,
      platformRotation: (json['platform_rotation'] as num?)?.toInt() ?? 0,
      platformPositionValid: json['platform_position_valid'] == true,
      calibrationVisualA: _pointFromJson(json['calibration_visual_a']),
      calibrationVisualB: _pointFromJson(json['calibration_visual_b']),
      calibrationVisualC: _pointFromJson(json['calibration_visual_c']),
      calibrationVisualD: _pointFromJson(json['calibration_visual_d']),
      calibrationVisualE: _pointFromJson(json['calibration_visual_e']),
      calibrationVisualF: _pointFromJson(json['calibration_visual_f']),
      calibrationPlatformA: _pointFromJson(json['calibration_platform_a']),
      calibrationPlatformB: _pointFromJson(json['calibration_platform_b']),
      calibrationPlatformC: _pointFromJson(json['calibration_platform_c']),
      calibrationPlatformD: _pointFromJson(json['calibration_platform_d']),
      calibrationPlatformE: _pointFromJson(json['calibration_platform_e']),
      calibrationPlatformF: _pointFromJson(json['calibration_platform_f']),
      calibrationValid: json['calibration_valid'] == true,
      calibrationScaleX: (json['calibration_scale_x'] as num?)?.toDouble() ?? 0,
      calibrationScaleY: (json['calibration_scale_y'] as num?)?.toDouble() ?? 0,
      calibrationAffineDeterminant:
          (json['calibration_affine_determinant'] as num?)?.toDouble() ?? 0,
      calibrationRmsError:
          (json['calibration_rms_error'] as num?)?.toDouble() ?? 0,
      calibrationMaxError:
          (json['calibration_max_error'] as num?)?.toDouble() ?? 0,
      assemblySplitY:
          (json['assembly_split_y'] as num?)?.toInt() ?? 0,
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
  final String greenMethod;
  final int greenHueMin;
  final int greenHueMax;
  final int greenSatMin;
  final int greenValMin;
  final int greenCloseKernel;
  final int greenCloseIter;
  final int paperCloseKernel;
  final int paperCloseIter;
  final int minPieceArea;
  final int cameraWidth;
  final int cameraHeight;
  final int roiX;
  final int roiY;
  final int roiWidth;
  final int roiHeight;
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
  final String serialActivePort;
  final bool serialReconnecting;
  final bool serialDevicePresent;
  final int serialBaud;
  final int serialPickZ;
  final int serialPlaceZ;
  final String serialLastReply;
  final String serialError;
  final List<Map<String, dynamic>> serialRawLog;
  final int serialEventRevision;
  final int platformX;
  final int platformY;
  final int platformZ;
  final int platformRotation;
  final bool platformPositionValid;
  final List<double>? calibrationVisualA;
  final List<double>? calibrationVisualB;
  final List<double>? calibrationVisualC;
  final List<double>? calibrationVisualD;
  final List<double>? calibrationVisualE;
  final List<double>? calibrationVisualF;
  final List<double>? calibrationPlatformA;
  final List<double>? calibrationPlatformB;
  final List<double>? calibrationPlatformC;
  final List<double>? calibrationPlatformD;
  final List<double>? calibrationPlatformE;
  final List<double>? calibrationPlatformF;
  final bool calibrationValid;
  final double calibrationScaleX;
  final double calibrationScaleY;
  final double calibrationAffineDeterminant;
  final double calibrationRmsError;
  final double calibrationMaxError;
  final int assemblySplitY;
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
  BackendBridge({
    String controlPath = '/tmp/puzzle_ui_control.json',
    this.backendDir = '/home/pi5/puzzle_card_detector',
  }) : _control = File(controlPath);

  final File _control;
  final File _state = File('/tmp/puzzle_ui_state.json');
  final File _frame = File('/tmp/puzzle_ui_frame.jpg');
  final File _binary = File('/tmp/puzzle_ui_binary.jpg');
  final File _result = File('/tmp/puzzle_ui_result.jpg');
  final String backendDir;
  int _frameRevision = -1;
  int _resultRevision = -1;
  Uint8List? _cachedResult;
  Process? _backendProcess;
  bool _restarting = false;
  int _lastRestartMs = 0;
  static const int _restartCooldownMs = 8000; // Don't restart more than once every 8s

  bool get isRestarting => _restarting;

  /// Whether enough time has passed since the last restart to try again.
  bool get _canRestart {
    return DateTime.now().millisecondsSinceEpoch - _lastRestartMs >=
        _restartCooldownMs;
  }

  /// Restart the Python backend process.
  ///
  /// Kills any existing backend processes and starts a fresh one
  /// in headless mode, the same way [start_ui.sh] does.
  Future<void> restartBackend() async {
    if (_restarting || !_canRestart) {
      return;
    }
    _restarting = true;
    _lastRestartMs = DateTime.now().millisecondsSinceEpoch;
    try {
      // Kill all existing backend processes
      await Process.run('pkill', ['-f', 'python3.*puzzle_card_detector/main.py']);
      // Brief pause to let the OS clean up
      await Future<void>.delayed(const Duration(milliseconds: 500));

      // Start the backend in headless mode
      _backendProcess = await Process.start(
        'python3',
        ['/home/pi5/puzzle_card_detector/main.py'],
        workingDirectory: backendDir,
        environment: {
          ...Platform.environment,
          'PUZZLE_HEADLESS': '1',
          'PUZZLE_PORTRAIT': '1',
          'PUZZLE_ROTATION': 'CW',
        },
        mode: ProcessStartMode.normal,
      );
      // Drain stdout/stderr to /tmp/puzzle_backend.log for debugging
      final logFile = File('/tmp/puzzle_backend.log');
      final sink = logFile.openWrite(mode: FileMode.writeOnlyAppend);
      sink.write(
        '\n=== Backend restarted at ${DateTime.now().toIso8601String()} ===\n',
      );
      _backendProcess!.stdout
          .transform(utf8.decoder)
          .listen((s) => sink.write(s));
      _backendProcess!.stderr
          .transform(utf8.decoder)
          .listen((s) => sink.write(s));
      _backendProcess!.exitCode.then((_) => sink.close());
    } on ProcessException {
      // Ignore — the process may already be gone or the binary missing
    } on FileSystemException {
      // Ignore
    } finally {
      _restarting = false;
    }
  }

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
    String? greenMethod,
    int? greenHueMin,
    int? greenHueMax,
    int? greenSatMin,
    int? greenValMin,
    int? greenCloseKernel,
    int? greenCloseIter,
    int? paperCloseKernel,
    int? paperCloseIter,
    int? minPieceArea,
    int? roiX,
    int? roiY,
    int? roiWidth,
    int? roiHeight,
    String? serialPort,
    int? serialBaud,
    int? serialPickZ,
    int? serialPlaceZ,
    int? armX,
    int? armY,
    int? armZ,
    int? armRotationCdeg,
    int? calibrationPreviewX,
    int? calibrationPreviewY,
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
    if (greenMethod != null) {
      payload['green_method'] = greenMethod;
    }
    if (greenHueMin != null) {
      payload['green_hue_min'] = greenHueMin;
    }
    if (greenHueMax != null) {
      payload['green_hue_max'] = greenHueMax;
    }
    if (greenSatMin != null) {
      payload['green_sat_min'] = greenSatMin;
    }
    if (greenValMin != null) {
      payload['green_val_min'] = greenValMin;
    }
    if (greenCloseKernel != null) {
      payload['green_close_kernel'] = greenCloseKernel;
    }
    if (greenCloseIter != null) {
      payload['green_close_iter'] = greenCloseIter;
    }
    if (paperCloseKernel != null) {
      payload['paper_close_kernel'] = paperCloseKernel;
    }
    if (paperCloseIter != null) {
      payload['paper_close_iter'] = paperCloseIter;
    }
    if (minPieceArea != null) {
      payload['min_piece_area'] = minPieceArea;
    }
    if (roiX != null) {
      payload['roi_x'] = roiX;
    }
    if (roiY != null) {
      payload['roi_y'] = roiY;
    }
    if (roiWidth != null) {
      payload['roi_width'] = roiWidth;
    }
    if (roiHeight != null) {
      payload['roi_height'] = roiHeight;
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
    if (calibrationPreviewX != null) {
      payload['calibration_preview_x'] = calibrationPreviewX;
    }
    if (calibrationPreviewY != null) {
      payload['calibration_preview_y'] = calibrationPreviewY;
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
