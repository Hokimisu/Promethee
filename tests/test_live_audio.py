import pytest

from promethee.live_audio import LiveAudio


class Backend:
    class CallbackAbort(Exception):
        pass

    def check_input_settings(self, **kwargs):
        pass

    def check_output_settings(self, **kwargs):
        pass

    def RawStream(self, **kwargs):
        self.callback = kwargs["callback"]
        self.active = False
        self.closed = False
        return self

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True

    def tick(self, status=False):
        outgoing = bytearray(b"x" * 960)
        self.callback(b"\1\0" * 480, outgoing, 480, None, status)
        return outgoing


def test_explicit_start_duplex_and_interruption():
    backend = Backend()
    audio = LiveAudio(backend=backend)
    assert not hasattr(backend, "callback")
    audio.start()
    audio.write(b"\2\0" * 600)
    assert backend.tick() == b"\2\0" * 480
    assert audio.readframes(480) == b"\1\0" * 480
    assert audio.clear_output() == 120
    assert backend.tick() == b"\0" * 960
    assert audio.rendered_samples == 480
    audio.close()
    audio.close()
    assert backend.closed and not backend.active
    with pytest.raises(ValueError, match="not active"):
        audio.write(b"\0\0")


def test_backpressure_is_bounded_and_explicit():
    backend = Backend()
    audio = LiveAudio(backend=backend)
    audio.start()
    try:
        audio.write(b"\0" * 48000)
        with pytest.raises(ValueError, match="one second"):
            audio.write(b"\0\0")
        for _ in range(25):
            backend.tick()
        with pytest.raises(Backend.CallbackAbort):
            backend.tick()
        with pytest.raises(ValueError, match="microphone_buffer_overflow"):
            audio.readframes(480)
    finally:
        audio.close()


def test_callback_does_not_wait_for_a_busy_consumer():
    backend = Backend()
    audio = LiveAudio(backend=backend)
    audio.start()
    try:
        with audio.lock, pytest.raises(Backend.CallbackAbort):
            backend.tick()
        with pytest.raises(ValueError, match="audio_callback_busy"):
            audio.readframes(480)
    finally:
        audio.close()


def test_missing_device_does_not_open_stream():
    backend = Backend()

    def missing(**kwargs):
        raise RuntimeError("No device")

    backend.check_input_settings = missing
    with pytest.raises(ValueError, match="do not support"):
        LiveAudio(backend=backend)
    assert not hasattr(backend, "callback")
