"""Bounded push-to-talk diagnostic: transcription -> the same Hermes host -> speech.

All state transitions and playback starts run on the UI thread. Device callbacks
only handle bounded PCM buffers. This is not the GPT-Live integration.
"""

import base64
import json
import queue
import sys
import threading
import time
from uuid import uuid4

from promethee.chat import WorkerProcess, open_text_host
from promethee.chat import configure as configure_chat
from promethee.execution import positive_seconds

RATE = 24000
INPUT_BYTES = RATE * 2 * 10
OUTPUT_BYTES = RATE * 2 * 60


def decode_pcm(encoded, limit):
    if not isinstance(encoded, str) or len(encoded) > (limit + 2) // 3 * 4:
        raise ValueError("Audio exceeds its limit.")
    pcm = base64.b64decode(encoded, validate=True)
    if not pcm or len(pcm) % 2 or len(pcm) > limit:
        raise ValueError("Expected bounded mono 24 kHz signed 16-bit PCM.")
    return pcm


class AudioDevice:
    def __init__(self, *, input_device=None, output_device=None):
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise ValueError("Install the voice extra and a working PortAudio device.") from exc
        self.sd = sd
        self.input_device, self.output_device = input_device, output_device
        self.stream = None
        self.buffer = bytearray()
        self.error = None

    def listen(self):
        self.stop()
        self.buffer = bytearray()
        self.error = None

        def receive(data, frames, timing, status):
            if status:
                self.error = "microphone_overflow"
                raise self.sd.CallbackAbort
            remaining = INPUT_BYTES - len(self.buffer)
            self.buffer.extend(bytes(data)[:remaining])
            if len(self.buffer) >= INPUT_BYTES:
                raise self.sd.CallbackStop

        try:
            self.stream = self.sd.RawInputStream(
                samplerate=RATE,
                channels=1,
                dtype="int16",
                blocksize=480,
                device=self.input_device,
                callback=receive,
            )
            self.stream.start()
        except Exception as exc:
            self.stop()
            raise ValueError("Microphone unavailable at 24 kHz mono.") from exc

    def finish_recording(self):
        self.stop()
        if self.error:
            raise ValueError(self.error)
        pcm = bytes(self.buffer)
        self.buffer.clear()
        if not pcm:
            raise ValueError("No audio recorded.")
        return pcm

    def play(self, pcm):
        self.stop()
        self.error = None
        cursor = 0

        def render(data, frames, timing, status):
            nonlocal cursor
            data[:] = b"\0" * len(data)
            if status:
                self.error = "speaker_underflow"
                raise self.sd.CallbackAbort
            block = pcm[cursor : cursor + len(data)]
            data[: len(block)] = block
            cursor += len(block)
            if cursor >= len(pcm):
                raise self.sd.CallbackStop

        try:
            self.stream = self.sd.RawOutputStream(
                samplerate=RATE,
                channels=1,
                dtype="int16",
                blocksize=480,
                device=self.output_device,
                callback=render,
            )
            self.stream.start()
        except Exception as exc:
            self.stop()
            raise ValueError("Audio output unavailable at 24 kHz mono.") from exc

    @property
    def active(self):
        return self.stream is not None and self.stream.active

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.abort()
            finally:
                self.stream.close()
                self.stream = None


class VoiceHost:
    def __init__(
        self,
        text_host,
        audio_factory,
        device,
        *,
        transcription_model,
        speech_model,
        voice,
        base_url,
        timeout=30,
        clock=time.monotonic,
    ):
        self.text_host, self.factory, self.device = text_host, audio_factory, device
        self.transcription_model, self.speech_model = transcription_model, speech_model
        self.voice, self.base_url = voice, base_url
        self.timeout, self.clock = positive_seconds(timeout), clock
        self.worker = None
        self.state = "idle"
        self.generation = None
        self.started = None
        self.world_id = text_host.store.service.runtime.require_session()["world_id"]

    def interrupt(self):
        started = self.clock()
        generation = self.generation
        self.generation = None  # Fence provider output before any potentially slow cleanup.
        self.state = "idle"
        try:
            self.device.stop()  # Discard queued playback before waiting on model processes.
        finally:
            try:
                self.text_host.close()  # Fences tools; does not cancel the body.
            finally:
                if self.worker:
                    self.worker.close()
                    self.worker = None
        return {
            "status": "interrupted",
            "cutoff_seconds": self.clock() - started,
            "world_id": self.world_id,
            "turn_id": self.text_host.turn_id,
            "generation": generation,
            "source": "chained-voice-diagnostic",
        }

    def listen(self):
        self.interrupt()
        self.generation = uuid4().hex
        self.started = self.clock()
        self.device.listen()
        self.state = "listening"

    def _audio(self, operation, **payload):
        self.deadline = self.clock() + self.timeout
        self.worker = self.factory(
            {
                "generation": self.generation,
                "operation": operation,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "model": self.transcription_model
                if operation == "transcribe"
                else self.speech_model,
                **payload,
            }
        )
        self.state = "transcribing" if operation == "transcribe" else "synthesizing"

    def finish_listening(self):
        if self.state != "listening":
            raise ValueError("No recording is active.")
        pcm = self.device.finish_recording()
        self._audio("transcribe", pcm=base64.b64encode(pcm).decode("ascii"))

    def text(self, message):
        self.interrupt()
        self.generation = uuid4().hex
        self.started = self.clock()
        self.text_host.start(message)
        self.state = "thinking"

    def poll(self):
        generation = self.generation
        result = self._poll()
        if result is not None:
            result.update(
                world_id=self.world_id,
                turn_id=self.text_host.turn_id,
                generation=generation,
                source="chained-voice-diagnostic",
            )
        return result

    def _poll(self):
        if self.state == "listening" and not self.device.active:
            self.finish_listening()
        if self.worker:
            if self.clock() >= self.deadline:
                self.interrupt()
                return {"status": "failed", "code": "audio_deadline_exceeded"}
            result = self.worker.poll()
            if result is None:
                return None
            self.worker.close()
            self.worker = None
            if result.get("generation") != self.generation or result.get("type") != "result":
                self.interrupt()
                return {"status": "failed", "code": "audio_provider_or_obsolete_response"}
            if self.state == "transcribing":
                text = result.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                    self.interrupt()
                    return {"status": "failed", "code": "invalid_transcription"}
                self.text_host.start(text)
                self.state = "thinking"
                return {"status": "transcribed", "text": text}
            pcm = decode_pcm(result.get("pcm"), OUTPUT_BYTES)
            self.device.play(pcm)
            self.state = "speaking"
            return {
                "status": "playback_started",
                "seconds_to_playback": self.clock() - self.started,
                "audio_seconds": len(pcm) / (RATE * 2),
                "billed_cost": None,
            }
        if self.state == "thinking":
            result = self.text_host.poll()
            if result is None:
                return None
            if result["status"] != "completed":
                self.state = "idle"
                return result
            text = result["text"]
            # Preserve the complete text answer; never truncate or summarize it with another brain.
            if len(text) > 2000:
                self.state = "idle"
                return {"status": "text_only", "code": "speech_text_limit", "text": text}
            self._audio("speak", text=text, voice=self.voice)
            return {"status": "answered", "text": text}
        if self.state == "speaking" and not self.device.active:
            self.device.stop()
            self.state = "idle"
            return {
                "status": "failed" if self.device.error else "playback_finished",
                "code": self.device.error,
                "heard_by_user": None,
            }
        return None


def configure(parser):
    configure_chat(parser)
    parser.add_argument("--transcription-model", required=True)
    parser.add_argument("--speech-model", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--audio-timeout", type=float, default=30)
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)


def run_voice(args):
    incoming = queue.Queue(maxsize=16)

    def read_input():
        while True:
            line = sys.stdin.readline(16002)
            incoming.put(line)
            if not line:
                return

    with open_text_host(args) as text_host:
        device = AudioDevice(input_device=args.input_device, output_device=args.output_device)
        host = VoiceHost(
            text_host,
            lambda request: WorkerProcess(
                [sys.executable, "-m", "promethee.voice_worker"], request
            ),
            device,
            transcription_model=args.transcription_model,
            speech_model=args.speech_model,
            voice=args.voice,
            base_url=args.base_url,
            timeout=args.audio_timeout,
        )
        threading.Thread(target=read_input, daemon=True).start()
        print(
            "Voix synthétique de diagnostic. Entrée : ouvrir/fermer le micro (10 s max). "
            "Un texte corrige la demande. /cancel coupe la réponse ; /quit ferme.",
            flush=True,
        )
        try:
            while True:
                try:
                    line = incoming.get_nowait()
                except queue.Empty:
                    line = None
                try:
                    if line is not None:
                        if not line or line.strip() == "/quit":
                            break
                        if not line.endswith("\n") or len(line.rstrip("\r\n")) > 16000:
                            raise ValueError("Input line exceeds 16000 characters.")
                        if line.strip() == "/cancel":
                            print(json.dumps(host.interrupt()), flush=True)
                        elif line.strip():
                            host.text(line.rstrip("\r\n"))
                        elif host.state == "listening":
                            host.finish_listening()
                        else:
                            host.listen()
                        continue  # Queued corrections take priority over playback starts.
                    result = host.poll()
                    if result:
                        print(json.dumps(result, ensure_ascii=False), flush=True)
                except (ValueError, OSError) as exc:
                    host.interrupt()
                    print(json.dumps({"status": "failed", "code": str(exc)}), flush=True)
                time.sleep(0.02)
        finally:
            host.interrupt()
