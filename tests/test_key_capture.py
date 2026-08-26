import unittest

from core import key_capture


class ClassifyKeyEventTests(unittest.TestCase):
    def test_windows_key_press_and_release_are_swallowed(self):
        for vk in (key_capture.VK_LWIN, key_capture.VK_RWIN):
            with self.subTest(vk=vk):
                self.assertEqual(
                    key_capture.classify_key_event(vk, 0, key_capture.WM_KEYDOWN),
                    (True, True),
                )
                self.assertEqual(
                    key_capture.classify_key_event(vk, 0, key_capture.WM_KEYUP),
                    (True, False),
                )

    def test_system_variants_of_the_windows_key_are_swallowed_too(self):
        self.assertEqual(
            key_capture.classify_key_event(
                key_capture.VK_LWIN, 0, key_capture.WM_SYSKEYDOWN
            ),
            (True, True),
        )
        self.assertEqual(
            key_capture.classify_key_event(
                key_capture.VK_LWIN, 0, key_capture.WM_SYSKEYUP
            ),
            (True, False),
        )

    def test_other_keys_reach_the_application(self):
        # 0x41 == "A": Qt still needs it to build the recorded combo.
        self.assertEqual(
            key_capture.classify_key_event(0x41, 0, key_capture.WM_KEYDOWN),
            (False, None),
        )

    def test_injected_windows_key_is_never_swallowed(self):
        # Shortcuts Mouser itself sends must not be eaten by the guard.
        self.assertEqual(
            key_capture.classify_key_event(
                key_capture.VK_LWIN,
                key_capture.LLKHF_INJECTED,
                key_capture.WM_KEYDOWN,
            ),
            (False, None),
        )

    def test_unknown_message_swallows_without_changing_state(self):
        swallow, super_down = key_capture.classify_key_event(
            key_capture.VK_LWIN, 0, 0x0007
        )
        self.assertTrue(swallow)
        self.assertIsNone(super_down)


class GuardFactoryTests(unittest.TestCase):
    def test_windows_gets_the_hook_guard(self):
        guard = key_capture.create_super_key_guard("win32")
        self.assertIsInstance(guard, key_capture.WindowsSuperKeyGuard)

    def test_other_platforms_get_the_no_op_guard(self):
        for platform_name in ("darwin", "linux", "freebsd"):
            with self.subTest(platform=platform_name):
                guard = key_capture.create_super_key_guard(platform_name)
                self.assertNotIsInstance(guard, key_capture.WindowsSuperKeyGuard)
                self.assertFalse(guard.start())
                self.assertFalse(guard.active)
                self.assertFalse(guard.super_held)
                guard.stop()  # must stay a no-op


class WindowsGuardStateTests(unittest.TestCase):
    """State bookkeeping is platform-independent; only the hook thread is not."""

    def setUp(self):
        self.guard = key_capture.WindowsSuperKeyGuard()

    def test_stop_without_start_is_safe(self):
        self.guard.stop()
        self.assertFalse(self.guard.active)
        self.assertFalse(self.guard.super_held)

    def test_super_state_changes_notify_once_per_transition(self):
        seen = []
        self.guard._on_super_changed = seen.append

        self.guard._set_super_held(True)
        self.guard._set_super_held(True)
        self.guard._set_super_held(False)

        self.assertEqual(seen, [True, False])
        self.assertFalse(self.guard.super_held)

    def test_stopping_releases_a_held_super_key(self):
        seen = []
        self.guard._on_super_changed = seen.append
        self.guard._set_super_held(True)

        self.guard.stop()

        self.assertFalse(self.guard.super_held)
        self.assertEqual(seen[-1], False)

    def test_callback_errors_do_not_escape_the_hook(self):
        def boom(_held):
            raise RuntimeError("UI went away")

        self.guard._on_super_changed = boom
        self.guard._set_super_held(True)  # must not raise
        self.assertTrue(self.guard.super_held)


if __name__ == "__main__":
    unittest.main()
