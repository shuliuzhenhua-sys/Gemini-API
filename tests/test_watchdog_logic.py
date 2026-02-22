import unittest

from gemini_webapi.client import GeminiClient


class TestWatchdogLogic(unittest.TestCase):
    def test_queueing_state_counts_as_progress(self):
        self.assertTrue(
            GeminiClient._should_reset_watchdog(
                got_update=False, is_thinking=False, is_queueing=True
            )
        )

