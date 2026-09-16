"""CPU-only contracts for the local session; never construct its live adapters."""

import collections
import copy
import importlib.util
import json
import queue
import sys
import threading
import types
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


def load_server():
    chat = types.ModuleType("promethee.chat")
    chat.open_text_host = Mock(side_effect=AssertionError("Live host forbidden"))
    body = types.ModuleType("body")
    body.BodyAdapter = Mock(side_effect=AssertionError("Live body forbidden"))
    spec = importlib.util.spec_from_file_location(
        "local_realtime_server_under_test", Path(__file__).with_name("serve.py")
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"promethee.chat": chat, "body": body}):
        spec.loader.exec_module(module)
    return module


server = load_server()


@pytest.fixture
def http_server(tmp_path):
    """Real HTTP sockets and handler, with a fake session that owns no models."""
    config = {"port": 0, "avatar": tmp_path / "unused.vrm"}
    bound = threading.Event()
    instances = []
    failures = []
    session = types.SimpleNamespace(
        lock=threading.RLock(),
        events=collections.deque(),
        cursor=0,
        sid="cpu-session",
        snapshot=Mock(return_value={"session_id": "cpu-session", "ready": True}),
        post=Mock(return_value={"ok": True}),
        stopping=threading.Event(),
        thread=Mock(),
        output=tmp_path,
    )

    class CountingServer(ThreadingHTTPServer):
        def __init__(self, address, handler):
            self.accepted_connections = 0
            super().__init__(address, handler)
            config["port"] = self.server_address[1]
            instances.append(self)

        def get_request(self):
            connection = super().get_request()
            self.accepted_connections += 1
            return connection

        def serve_forever(self):
            bound.set()
            super().serve_forever(poll_interval=0.01)

    def run():
        try:
            server.main()
        except BaseException as exc:
            failures.append(exc)
            bound.set()

    with (
        patch.object(sys, "argv", ["serve.py", "--config", "unused.json"]),
        patch.object(server, "load_configuration", return_value=config),
        patch.object(Path, "is_file", return_value=True),
        patch.object(server, "ThreadingHTTPServer", CountingServer),
        patch.object(server, "Session", return_value=session),
    ):
        owner = threading.Thread(target=run)
        owner.start()
        try:
            assert bound.wait(3), "HTTP test server did not start"
            assert not failures
            yield instances[0], session
        finally:
            if instances:
                instances[0].shutdown()
            owner.join(3)
        assert not owner.is_alive()
        assert not failures


def test_http_polls_and_valid_post_reuse_one_real_connection(http_server):
    httpd, session = http_server
    port = httpd.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        first_socket = None
        for index in range(200):
            connection.request("GET", "/state.json" if index % 2 == 0 else "/events?after=0")
            response = connection.getresponse()
            assert response.status == 200 and response.version == 11
            assert not response.will_close
            raw = response.read()
            assert len(raw) == int(response.getheader("Content-Length"))
            assert json.loads(raw)["session_id"] == "cpu-session"
            if first_socket is None:
                first_socket = connection.sock
            assert connection.sock is first_socket
        connection.request(
            "POST",
            "/telemetry",
            body="{}",
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
        )
        response = connection.getresponse()
        assert response.status == 200 and not response.will_close
        assert json.loads(response.read()) == {"ok": True}
        session.post.assert_called_once_with("telemetry", {})
        assert connection.sock is first_socket
        assert httpd.accepted_connections == 1
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/say", {"Origin": "http://unexpected.invalid"}, 403),
        ("/unknown", {}, 404),
        ("/say", {"Content-Type": "text/plain"}, 400),
        ("/say", {"Content-Length": "20000"}, 400),
        ("/say", {"Transfer-Encoding": "chunked"}, 400),
    ],
)
def test_http_rejected_post_closes_unread_body(http_server, path, headers, status):
    httpd, session = http_server
    port = httpd.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    request_headers = {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{port}",
        **headers,
    }
    try:
        connection.request("POST", path, body="{}", headers=request_headers)
        response = connection.getresponse()
        assert response.status == status
        assert response.will_close and response.getheader("Connection") == "close"
        response.read()
        assert connection.sock is None
        session.post.assert_not_called()
    finally:
        connection.close()


def test_http_client_requested_close_is_honored(http_server):
    httpd, _session = http_server
    connection = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3)
    try:
        connection.request("GET", "/state.json", headers={"Connection": "close"})
        response = connection.getresponse()
        assert response.status == 200 and response.will_close
        assert response.getheader("Connection") == "close"
        response.read()
        assert connection.sock is None
    finally:
        connection.close()


def test_busy_port_fails_before_constructing_models():
    with (
        patch.object(sys, "argv", ["serve.py", "--config", "unused.json"]),
        patch.object(
            server, "load_configuration", return_value={"port": 2392, "avatar": Path("a")}
        ),
        patch.object(Path, "is_file", return_value=True),
        patch.object(server, "ThreadingHTTPServer", side_effect=OSError("port already in use")),
        patch.object(server, "Session") as session,
    ):
        import pytest

        with pytest.raises(OSError, match="port already"):
            server.main()
        session.assert_not_called()


class SessionContracts(unittest.TestCase):
    def setUp(self):
        # __init__ starts adapters and an owner thread, so explicitly bypass it.
        self.session = server.Session.__new__(server.Session)
        item = self.session
        item.lock = threading.RLock()
        item.commands = queue.Queue(maxsize=1)
        item.events = collections.deque(maxlen=640)
        item.cursor = 17
        item.sid = "existing-session"
        item.active_sid = item.sid
        item.vox_ready = True
        item.asr = None
        item.asr_status = {"state": "disabled", "error": None}
        item.input_capture = None
        item.input_ids = set()
        item.pending_audio = None
        item.auto_continue = True
        item.state = {
            "ready": True,
            "session_id": item.sid,
            "phase": "speaking",
            "text": "Current speech",
        }
        item.host = Mock()
        item.body = Mock()
        item.body.poll.return_value = {"ready": True}
        item.pending_text = {"id": "pending", "text": "Next speech"}
        item.speech = {"id": "current-speech", "turn_id": "current-turn"}
        item.vox_send = Mock()
        item.output = Path("unused-local-output")

    def test_interrupt_without_notify_cancels_voice_without_global_stop(self):
        item = self.session
        item.interrupt(notify=False)
        item.host.cancel.assert_called_once_with()
        item.body.set_presence.assert_called_once_with(False)
        item.vox_send.assert_called_once_with({"op": "cancel", "id": "current-speech"})
        item.host.store.speech_delivery.assert_called_once_with(
            "current-turn", "current-speech", "interrupted"
        )
        self.assertIsNone(item.speech)
        self.assertIsNone(item.pending_text)
        self.assertEqual(list(item.events), [])
        self.assertEqual(item.cursor, 17)
        self.assertEqual(item.sid, "existing-session")
        item.body.cancel.assert_not_called()

    def test_interrupt_with_notify_emits_one_global_stop(self):
        item = self.session
        item.interrupt(notify=True)
        item.vox_send.assert_called_once_with({"op": "cancel", "id": "current-speech"})
        self.assertEqual(
            list(item.events), [{"cursor": 18, "session_id": "existing-session", "event": "stop"}]
        )
        item.body.cancel.assert_not_called()

    def test_interrupt_body_cancel_is_independent_of_notify(self):
        item = self.session
        item.interrupt(body=True, notify=False)
        item.body.cancel.assert_called_once_with()
        self.assertEqual(list(item.events), [])

    def test_interrupt_without_speech_still_notifies_but_sends_no_voice_cancel(self):
        item = self.session
        item.speech = None
        item.interrupt(notify=True)
        item.vox_send.assert_not_called()
        item.host.store.speech_delivery.assert_not_called()
        self.assertEqual([event["event"] for event in item.events], ["stop"])

    def test_post_changes_fence_only_after_successful_queue_insertion(self):
        for operation, value in (
            ("start", {"scenario": "A neutral test scene"}),
            ("say", {"text": "A neutral intervention"}),
            ("stop", {}),
        ):
            with self.subTest(operation=operation):
                self.setUp()
                item = self.session
                original = copy.deepcopy(item.state)
                real_queue = item.commands

                def insert(command, item=item, original=original, real_queue=real_queue):
                    self.assertEqual(item.sid, "existing-session")
                    self.assertEqual(item.state, original)
                    real_queue.put_nowait(command)
                    self.assertEqual(item.sid, "existing-session")
                    self.assertEqual(item.state, original)

                item.commands = Mock(put_nowait=Mock(side_effect=insert))
                result = item.post(operation, value)
                queued_operation, queued_value = real_queue.get_nowait()
                self.assertEqual(queued_operation, operation)
                self.assertEqual(queued_value["session_id"], result["session_id"])
                self.assertEqual(item.sid, result["session_id"])
                self.assertNotEqual(item.sid, "existing-session")
                self.assertEqual(item.state["session_id"], item.sid)
                self.assertEqual(
                    item.state["phase"], "stopping" if operation == "stop" else "thinking"
                )
                self.assertEqual(result["stopped"], operation == "stop")
                self.assertNotIn("session_id", value)
                item.vox_send.assert_not_called()

    def test_full_queue_preserves_existing_fence_state_and_speech(self):
        for operation, value in (
            ("start", {"scenario": "A neutral test scene"}),
            ("say", {"text": "A neutral intervention"}),
            ("stop", {}),
            ("telemetry", {"session_id": "existing-session"}),
        ):
            with self.subTest(operation=operation):
                self.setUp()
                item = self.session
                previous_command = ("say", {"text": "Already queued"})
                item.commands.put_nowait(previous_command)
                before = copy.deepcopy((item.sid, item.state, item.speech, item.pending_text))
                with self.assertRaises(queue.Full):
                    item.post(operation, value)
                self.assertEqual((item.sid, item.state, item.speech, item.pending_text), before)
                self.assertEqual(item.cursor, 17)
                self.assertEqual(list(item.events), [])
                self.assertEqual(item.commands.get_nowait(), previous_command)
                item.vox_send.assert_not_called()
                item.host.cancel.assert_not_called()
                item.body.cancel.assert_not_called()

    def test_telemetry_does_not_replace_session_fence(self):
        item = self.session
        before = copy.deepcopy(item.state)
        value = {"session_id": item.sid, "event": "playback_started", "id": "current-speech"}
        self.assertEqual(item.post("telemetry", value), {"ok": True})
        self.assertEqual(item.commands.get_nowait(), ("telemetry", value))
        self.assertEqual(item.sid, "existing-session")
        self.assertEqual(item.state, before)

    def test_owner_cannot_discard_command_before_publisher_sets_fence(self):
        item = self.session
        inserted = threading.Event()
        dequeued = threading.Event()
        owner_reached_boundary = threading.Event()
        original_queue = item.commands
        original_lock = item.lock
        owner_id = threading.get_ident()
        failures = []

        class PublicationLock:
            def __enter__(self):
                if inserted.is_set() and dequeued.is_set() and threading.get_ident() == owner_id:
                    # The fixed consumer waits here until the publisher finishes.
                    owner_reached_boundary.set()
                original_lock.acquire()
                return self

            def __exit__(self, *_):
                original_lock.release()

        class PausedPublicationQueue:
            def put_nowait(self, command):
                original_queue.put_nowait(command)
                inserted.set()
                if not owner_reached_boundary.wait(3):
                    raise TimeoutError("Owner did not reach the publication boundary")

            def get_nowait(self):
                command = original_queue.get_nowait()
                dequeued.set()
                return command

        item.commands = PausedPublicationQueue()
        item.lock = PublicationLock()
        item.stopping = threading.Event()
        item.vox_events = queue.Queue()
        item.speech = None
        item.pending_text = None
        item.running = False
        item.began = None
        item.calls = 0
        item.metric = {}
        item.next_metrics_write = float("inf")
        item.think = Mock()

        def poll_once():
            # Before the fix, the stale comparison drops the command and reaches
            # this point without waiting on PublicationLock. Release either case.
            owner_reached_boundary.set()
            item.stopping.set()
            return None

        item.host.poll.side_effect = poll_once

        def publish():
            try:
                item.post("say", {"text": "A neutral intervention"})
            except BaseException as exc:
                failures.append(exc)

        publisher = threading.Thread(target=publish)
        publisher.start()
        try:
            self.assertTrue(inserted.wait(3))
            item.loop()
        finally:
            owner_reached_boundary.set()
            publisher.join(3)
        self.assertFalse(publisher.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(original_queue.empty())
        self.assertNotEqual(item.sid, "existing-session")
        item.think.assert_called_once_with(
            "A neutral intervention", first=False, expected_sid=item.sid
        )

    def test_invalid_or_not_ready_request_preserves_fence_and_queue(self):
        item = self.session
        before = copy.deepcopy(item.state)
        with self.assertRaises(ValueError):
            item.post("say", {"text": "   "})
        item.vox_ready = False
        with self.assertRaises(ValueError):
            item.post("start", {"scenario": "A neutral test scene"})
        self.assertEqual(item.sid, "existing-session")
        self.assertEqual(item.state, before)
        self.assertTrue(item.commands.empty())

    def test_chosen_direction_reaches_vox_but_not_spoken_text(self):
        item = self.session
        speech = {
            "id": "next",
            "turn_id": "turn",
            "text": "Quelle bonne surprise.",
            "delivery": "Quiet delight, smiling and gentle.",
            "sid": item.sid,
        }
        with patch("pathlib.Path.open", unittest.mock.mock_open()):
            item.speak(speech)
        request = item.vox_send.call_args.args[0]
        item.body.set_presence.assert_called_once_with(True)
        self.assertEqual(request["text"], speech["text"])
        self.assertIn(speech["delivery"], request["style"])
        self.assertEqual(list(item.events)[0]["delivery"], speech["delivery"])

    def test_obsolete_reply_cannot_be_relabelled_as_new_session(self):
        item = self.session
        item.sid = "new-session"
        item.speak({"id": "old", "sid": "existing-session"})
        item.vox_send.assert_not_called()
        item.body.set_presence.assert_not_called()
        self.assertEqual(list(item.events), [])

    def test_tag_is_sent_to_voice_but_hidden_in_subtitle(self):
        item = self.session
        speech = {
            "id": "next",
            "turn_id": "turn",
            "text": "[laughing] Tu progresses… enfin !",
            "delivery": "Playfully impressed (softly).",
            "sid": item.sid,
        }
        with patch("pathlib.Path.open", unittest.mock.mock_open()):
            item.speak(speech)
        request = item.vox_send.call_args.args[0]
        self.assertEqual(request["text"], "[laughing] Tu progresses… enfin !")
        self.assertNotIn("(", request["style"])
        self.assertEqual(list(item.events)[0]["text"], "Tu progresses… enfin !")
        self.assertEqual(item.state["text"], "Tu progresses… enfin !")


if __name__ == "__main__":
    unittest.main(verbosity=2)
