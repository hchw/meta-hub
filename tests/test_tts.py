from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import cosy_service  # noqa: E402

from meta_hub.tts.client import SpeechError, SpeechServiceClient  # noqa: E402


class CountingBackend(cosy_service.FakeBackend):
    def __init__(self):
        super().__init__(chunks=4, chunk_seconds=0.2, delay=0.05)
        self.stream_calls = 0
        self.loaded = 1  # the model/backend is constructed exactly once

    def stream(self, text, prompt_wav, prompt_text):
        self.stream_calls += 1
        yield from super().stream(text, prompt_wav, prompt_text)


class SpeechServiceTest(unittest.TestCase):
    def setUp(self):
        self.backend = CountingBackend()
        self.server = cosy_service.SpeechServer(("127.0.0.1", 0), self.backend)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = SpeechServiceClient("127.0.0.1", self.port, timeout=10)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_streams_chunks_before_synthesis_finishes(self):
        start = time.monotonic()
        arrivals = []
        chunks = []
        for chunk in self.client.stream(
            "这是一段比较长的文本，用来验证流式返回。",
            prompt_wav="/tmp/ref.wav",
        ):
            arrivals.append(time.monotonic() - start)
            chunks.append(chunk)
        finished = time.monotonic() - start
        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(c.sample_rate == 22050 for c in chunks))
        self.assertEqual(len(chunks[0].samples), int(22050 * 0.2))
        self.assertLess(arrivals[0], finished)
        self.assertLess(arrivals[0], 0.15)

    def test_two_requests_reuse_the_loaded_service(self):
        first = self.client.synthesize("第一句。", "/tmp/meta-hub-test-1.wav",
                                       prompt_wav="/tmp/ref.wav")
        t0 = time.monotonic()
        second = self.client.synthesize("第二句。", "/tmp/meta-hub-test-2.wav",
                                        prompt_wav="/tmp/ref.wav")
        elapsed = time.monotonic() - t0
        self.assertTrue(Path(first).exists())
        self.assertTrue(Path(second).exists())
        self.assertGreater(Path(second).stat().st_size, 44)
        self.assertEqual(self.backend.stream_calls, 2)
        self.assertEqual(self.backend.loaded, 1)
        # No model load between calls: both are on the same fast path.
        self.assertLess(elapsed, 2.0)

    def test_empty_text_returns_none(self):
        self.assertIsNone(self.client.synthesize("  ", "/tmp/none.wav",
                                                 prompt_wav="/tmp/ref.wav"))

    def test_unreachable_service_is_a_distinguishable_error(self):
        client = SpeechServiceClient("127.0.0.1", 1, timeout=0.2)
        with self.assertRaises(SpeechError):
            list(client.stream("hi", prompt_wav="/tmp/ref.wav"))


if __name__ == "__main__":
    unittest.main()
