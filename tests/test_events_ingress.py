from __future__ import annotations

import time
import unittest

from meta_hub.events import Event, EventError, EventKind
from meta_hub.ingress.base import IngressError, ReconnectingIngress
from meta_hub.ingress.fake import ListAdapter, ScriptedAdapter, ScriptedEntry


class EventConstructionTest(unittest.TestCase):
    def test_comment(self):
        e = Event.comment("u1", "hello", viewer_name="Ann")
        self.assertEqual(e.kind, EventKind.COMMENT)
        self.assertEqual(e.text, "hello")
        self.assertEqual(e.viewer_name, "Ann")
        self.assertTrue(e.event_id)
        self.assertGreater(e.ts, 0)

    def test_gift(self):
        e = Event.gift("u1", "rose", 3, gift_name="玫瑰", value=300)
        self.assertEqual(e.kind, EventKind.GIFT)
        self.assertEqual(e.gift_count, 3)
        self.assertEqual(e.gift_value, 300)
        self.assertGreaterEqual(e.priority, 90)
        self.assertTrue(e.is_high_value(100))

    def test_enter_like(self):
        self.assertEqual(Event.enter("u2").kind, EventKind.ENTER)
        self.assertEqual(Event.like("u2", 9).gift_count, 9)

    def test_fansclub_follow(self):
        f = Event.fansclub("u3", "join")
        self.assertEqual(f.reason, "join")
        g = Event.follow("u3", "unfollow")
        self.assertEqual(g.direction, "unfollow")

    def test_roundtrip_and_unknown_kind(self):
        e = Event.gift("u1", "rose", 2, value=50, event_id="fixed")
        self.assertEqual(Event.from_dict(e.to_dict()), e)
        with self.assertRaises(EventError):
            Event.from_dict({"kind": "wat"})

    def test_priority_order(self):
        self.assertGreater(Event.gift("u", "r", value=2000).priority,
                           Event.comment("u", "hi").priority)
        self.assertGreater(Event.comment("u", "hi").priority,
                           Event.like("u").priority)


class ScriptedSourceTest(unittest.TestCase):
    def test_replays_in_order(self):
        events = [Event.comment("u", f"m{i}") for i in range(3)]
        adapter = ScriptedAdapter([ScriptedEntry(0.0, e) for e in events])
        ingress = ReconnectingIngress(adapter, poll_timeout=0.01, heartbeat_interval=0)
        got = []
        for event in ingress.stream():
            got.append(event)
            if len(got) == 3:
                break
        self.assertEqual([e.text for e in got], ["m0", "m1", "m2"])

    def test_timeline_delays(self):
        events = [
            ScriptedEntry(0.0, Event.comment("u", "now")),
            ScriptedEntry(0.2, Event.comment("u", "later")),
        ]
        adapter = ScriptedAdapter(events)
        ingress = ReconnectingIngress(adapter, poll_timeout=0.01, heartbeat_interval=0)
        start = time.monotonic()
        got = []
        for event in ingress.stream():
            got.append((time.monotonic() - start, event.text))
            if len(got) == 2:
                break
        self.assertEqual(got[0][1], "now")
        self.assertEqual(got[1][1], "later")
        self.assertGreaterEqual(got[1][0] - got[0][0], 0.15)


class ReconnectAndDedupTest(unittest.TestCase):
    def test_reconnects_and_dedups_redelivery(self):
        e = Event.comment("u", "once", event_id="same")
        second = Event.comment("u", "second", event_id="other")
        adapter = ListAdapter([e, e, second])

        def no_sleep(_):
            pass

        ingress = ReconnectingIngress(adapter, poll_timeout=0.0,
                                      heartbeat_interval=0, sleep=no_sleep,
                                      reconnect_min=0, reconnect_max=0)
        got = []
        ingress.run(got.append, max_events=2)
        self.assertEqual([event.text for event in got], ["once", "second"])
        self.assertEqual(ingress.stats.reconnects, 0)
        self.assertEqual(ingress.stats.duplicates, 1)
        # ListAdapter restarts on reconnect, so the already-seen event is dropped.
        self.assertTrue(ingress._is_duplicate(e))

    def test_heartbeat_sent_on_interval(self):
        class HeartbeatAdapter(ListAdapter):
            beats = 0

            def heartbeat(self):
                self.beats += 1

        adapter = HeartbeatAdapter([])
        now = {"t": 0.0}
        ingress = ReconnectingIngress(adapter, heartbeat_interval=1.0,
                                      monotonic=lambda: now["t"])
        ingress.adapter.connect()
        ingress._connected = True
        ingress._last_heartbeat = 0.0
        now["t"] = 1.5
        ingress._heartbeat_if_due()
        self.assertEqual(adapter.beats, 1)
        now["t"] = 1.8
        ingress._heartbeat_if_due()
        self.assertEqual(adapter.beats, 1)
        now["t"] = 2.6
        ingress._heartbeat_if_due()
        self.assertEqual(adapter.beats, 2)


if __name__ == "__main__":
    unittest.main()


class TcpAdapterTest(unittest.TestCase):
    def test_receives_events_and_sends_heartbeat(self):
        import json
        import socketserver
        import threading

        from meta_hub.ingress.base import TcpJsonAdapter

        received = []

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                event = Event.comment("u1", "over tcp", event_id="tcp-1")
                self.request.sendall((json.dumps(event.to_dict()) + "\n").encode())
                self.request.settimeout(2)
                try:
                    received.append(self.request.recv(4096))
                except OSError:
                    pass

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = TcpJsonAdapter("127.0.0.1", port)
            adapter.connect()
            event = adapter.receive(1.0)
            self.assertEqual(event.text, "over tcp")
            adapter.heartbeat()
            time.sleep(0.1)
            self.assertTrue(any(b"heartbeat" in chunk for chunk in received))
        finally:
            adapter.close()
            server.shutdown()
            server.server_close()
