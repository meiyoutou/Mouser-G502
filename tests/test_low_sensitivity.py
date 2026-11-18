"""Actual low-distance recognition, VAD values and isolated config writes."""
import copy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.gesture_recognizer import GestureRecognizer
from core.speech_session import create_vad


class LowDistanceTests(unittest.TestCase):
    def recognizer(self, threshold):
        output = []
        rec = GestureRecognizer(output.append)
        rec.configure(enabled=True, threshold=threshold, commit_window_ms=400,
                      settle_ms=90, cross_ratio=0.5)
        rec.begin()
        return rec, output

    def test_one_pixel_fires_in_each_direction(self):
        for x, y, expected in ((1, 0, 'right'), (-1, 0, 'left'), (0, 1, 'down'), (0, -1, 'up')):
            rec, output = self.recognizer(1)
            rec.sample(x, y, now=1.0)
            self.assertEqual(output, [expected])

    def test_one_pixel_is_not_enough_at_original_twenty_pixel_setting(self):
        rec, output = self.recognizer(20)
        rec.sample(1, 0, now=1.0)
        self.assertEqual(output, [])

    def test_subthreshold_and_diagonal_noise_do_not_fire_at_one_pixel(self):
        for dx, dy in ((0.5, 0), (1, 1), (0, 0)):
            rec, output = self.recognizer(1)
            rec.sample(dx, dy, now=1.0)
            self.assertEqual(output, [])

    def test_low_distance_return_rearms_same_direction_and_not_opposite(self):
        rec, output = self.recognizer(1)
        rec.sample(1, 0, now=1.0)
        rec.sample(-1, 0, now=1.04)
        rec.sample(1, 0, now=1.13)
        self.assertEqual(output, ['right', 'right'])


class ActualVadTests(unittest.TestCase):
    def test_small_values_reach_detector_not_old_floors(self):
        config = SimpleNamespace(silero_vad=SimpleNamespace())
        seen = []
        fake = SimpleNamespace(VadModelConfig=lambda: config,
                               VoiceActivityDetector=lambda cfg, **kw: seen.append(cfg))
        with patch.dict(sys.modules, {'sherpa_onnx': fake}), patch('core.speech_session.bundled_path', return_value='synthetic.onnx'):
            create_vad({'vad_threshold': 0.01, 'silence_stop_seconds': 0.1})
        self.assertEqual(seen[0].silero_vad.threshold, 0.01)
        self.assertEqual(seen[0].silero_vad.min_silence_duration, 0.1)

    def test_existing_vad_values_are_preserved(self):
        config = SimpleNamespace(silero_vad=SimpleNamespace())
        fake = SimpleNamespace(VadModelConfig=lambda: config, VoiceActivityDetector=lambda cfg, **kw: cfg)
        with patch.dict(sys.modules, {'sherpa_onnx': fake}), patch('core.speech_session.bundled_path', return_value='synthetic.onnx'):
            result = create_vad({'vad_threshold': 0.5, 'silence_stop_seconds': 1.2})
        self.assertEqual(result.silero_vad.threshold, 0.5)
        self.assertEqual(result.silero_vad.min_silence_duration, 1.2)


class LowSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_use_real_low_values_and_preserve_shortcuts(self):
        from core.config import DEFAULT_CONFIG
        from ui.backend import Backend
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        with patch('ui.backend.load_config', return_value=cfg), patch('ui.backend.save_config'), patch('ui.backend.supports_login_startup', return_value=False):
            backend = Backend()
            profiles = copy.deepcopy(backend._cfg['profiles'])
            backend.setGestureThreshold(1)
            backend.setActionsRingHoldMs(1)
            backend.setHscrollThresholdPercent(1)
            backend.setHscrollRepeatMs(1)
            backend.setSpeechSetting('vad_threshold', 0.01)
            backend.setSpeechSetting('silence_stop_seconds', 0.1)
            settings = backend._cfg['settings']
            self.assertEqual(settings['gesture_threshold'], 1)
            self.assertEqual(settings['actions_ring_hold_ms'], 1)
            self.assertEqual(settings['hscroll_threshold'], 0.01)
            self.assertEqual(settings['hscroll_action_cooldown_ms'], 1)
            self.assertEqual(settings['speech_to_text']['vad_threshold'], 0.01)
            self.assertEqual(settings['speech_to_text']['silence_stop_seconds'], 0.1)
            backend.setSpeechSetting('vad_threshold', float('nan'))
            self.assertEqual(settings['speech_to_text']['vad_threshold'], 0.01)
            self.assertEqual(backend._cfg['profiles'], profiles)
            backend._finishSpeechPackInstall({'ok': False, 'code': 'network', 'error': 'TIMEOUT'})
            self.assertIn('TIMEOUT', backend.speechInstallMessage)
            backend.deleteLater()

    def test_new_horizontal_one_hundred_percent_survives_save_reload(self):
        import json
        import tempfile
        from pathlib import Path
        from core import config
        cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg['settings']['hscroll_threshold'] = 1.0
        cfg['settings']['hscroll_threshold_scale_version'] = 2
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'config.json'
            target.write_text(json.dumps(cfg), encoding='utf-8')
            with patch.object(config, 'CONFIG_DIR', folder), patch.object(config, 'CONFIG_FILE', str(target)):
                reloaded = config.load_config()
        self.assertEqual(reloaded['settings']['hscroll_threshold'], 1.0)
        self.assertEqual(reloaded['profiles'], cfg['profiles'])


class ActualHorizontalScrollTests(unittest.TestCase):
    def test_one_percent_delta_fires_and_one_millisecond_repeat_is_real(self):
        from tests.test_engine import EngineHorizontalScrollTests, MouseEvent
        engine = EngineHorizontalScrollTests()._make_engine(hscroll_threshold=0.01)
        engine.cfg['settings']['hscroll_action_cooldown_ms'] = 1
        handler = engine._make_hscroll_handler('space_left')
        with patch('core.engine.execute_action') as execute:
            for timestamp in (1.0, 1.0005, 1.002):
                handler(SimpleNamespace(event_type=MouseEvent.HSCROLL_LEFT, raw_data=0.01, timestamp=timestamp))
        self.assertEqual(execute.call_count, 2)

    def test_default_distance_does_not_fire_on_one_percent_delta(self):
        from tests.test_engine import EngineHorizontalScrollTests, MouseEvent
        engine = EngineHorizontalScrollTests()._make_engine(hscroll_threshold=0.1)
        handler = engine._make_hscroll_handler('space_left')
        with patch('core.engine.execute_action') as execute:
            handler(SimpleNamespace(event_type=MouseEvent.HSCROLL_LEFT, raw_data=0.01, timestamp=1.0))
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
