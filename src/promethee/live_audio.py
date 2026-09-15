"""Bounded duplex PortAudio buffers; no reasoning or network work in callbacks."""

import threading
from collections import deque


class LiveAudio:
    def __init__(self, *, input_device=None, output_device=None, backend=None):
        if backend is None:
            try:
                import sounddevice as backend
            except (ImportError, OSError) as exc:
                raise ValueError("Install the voice extra and PortAudio support.") from exc
        self.backend = backend
        self.devices = (input_device, output_device)
        self.lock = threading.Lock()
        self.input, self.output = deque(), bytearray()
        self.stream, self.error = None, None
        self.running, self.rendered_samples = False, 0
        try:
            backend.check_input_settings(
                device=input_device, channels=1, dtype="int16", samplerate=24000
            )
            backend.check_output_settings(
                device=output_device, channels=1, dtype="int16", samplerate=24000
            )
        except Exception as exc:
            raise ValueError(
                "Selected microphone/output do not support mono PCM16 at 24 kHz."
            ) from exc

    def start(self):
        if self.stream is not None:
            raise ValueError("Audio device is already open.")
        self.error = None
        self.running = True

        def callback(incoming, outgoing, frames, timing, status):
            outgoing[:] = b"\0" * len(outgoing)
            if not self.lock.acquire(blocking=False):
                self.error = "audio_callback_busy"
                raise self.backend.CallbackAbort
            try:
                if not self.running:
                    return
                if status or frames != 480 or len(incoming) != 960 or len(outgoing) != 960:
                    self.error = "audio_device_stream_error"
                elif len(self.input) >= 25:
                    self.error = "microphone_buffer_overflow"
                if self.error:
                    raise self.backend.CallbackAbort
                self.input.append(bytes(incoming))
                count = min(len(outgoing), len(self.output))
                outgoing[:count] = self.output[:count]
                del self.output[:count]
                self.rendered_samples += count // 2
            finally:
                self.lock.release()

        try:
            self.stream = self.backend.RawStream(
                samplerate=24000,
                channels=(1, 1),
                dtype="int16",
                blocksize=480,
                device=self.devices,
                callback=callback,
            )
            self.stream.start()
        except Exception as exc:
            self.close()
            raise ValueError("Could not start the selected audio devices.") from exc

    def _check(self):
        if self.error or not self.running or self.stream is None or not self.stream.active:
            raise ValueError(self.error or "Audio stream is not active.")

    def readframes(self, frames):
        if frames != 480:
            raise ValueError("Live capture uses 480-frame blocks.")
        with self.lock:
            self._check()
            return self.input.popleft() if self.input else b""

    def write(self, pcm):
        if not isinstance(pcm, bytes) or len(pcm) % 2:
            raise ValueError("Expected PCM16 bytes.")
        with self.lock:
            self._check()
            if len(self.output) + len(pcm) > 48000:
                raise ValueError("Playback buffer exceeds one second.")
            self.output.extend(pcm)

    def clear_output(self):
        with self.lock:
            discarded = len(self.output) // 2
            self.output.clear()
            return discarded

    def close(self):
        with self.lock:
            self.running = False
            self.input.clear()
            self.output.clear()
            stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()
