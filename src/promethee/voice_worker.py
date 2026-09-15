"""One killable OpenAI Audio API request; no conversation state or body tools."""

import base64
import io
import json
import os
import sys
import wave

from promethee.voice import INPUT_BYTES, OUTPUT_BYTES, RATE, decode_pcm


def process(request):
    from openai import OpenAI

    operation = request["operation"]
    shared = {"generation", "operation", "base_url", "timeout", "model"}
    expected = shared | ({"pcm"} if operation == "transcribe" else {"text", "voice"})
    if operation not in {"transcribe", "speak"} or set(request) != expected:
        raise ValueError("Invalid audio request.")
    with OpenAI(
        api_key=os.environ["PROMETHEE_OPENAI_API_KEY"],
        base_url=request["base_url"],
        timeout=request["timeout"],
        max_retries=0,
    ) as client:
        if operation == "transcribe":
            pcm = decode_pcm(request["pcm"], INPUT_BYTES)
            wav = io.BytesIO()
            with wave.open(wav, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes(pcm)
            transcription = client.audio.transcriptions.create(
                model=request["model"],
                file=("recording.wav", wav.getvalue(), "audio/wav"),
            )
            text = transcription.text
            if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                raise ValueError("Invalid transcription.")
            payload = {"text": text}
        else:
            if not isinstance(request["text"], str) or not 1 <= len(request["text"]) <= 2000:
                raise ValueError("Speech text exceeds limit.")
            pcm = bytearray()
            with client.audio.speech.with_streaming_response.create(
                model=request["model"],
                voice=request["voice"],
                input=request["text"],
                response_format="pcm",
            ) as response:
                for chunk in response.iter_bytes(8192):
                    pcm.extend(chunk)
                    if len(pcm) > OUTPUT_BYTES:
                        raise ValueError("Speech exceeds 60 seconds.")
            encoded = base64.b64encode(pcm).decode("ascii")
            decode_pcm(encoded, OUTPUT_BYTES)
            payload = {"pcm": encoded}
    return {"type": "result", "generation": request["generation"], **payload}


def main():
    try:
        line = sys.stdin.readline(1_048_577)
        if len(line) > 1_048_576 or not line.endswith("\n"):
            raise ValueError("Invalid request frame.")
        result = process(json.loads(line))
    except Exception:
        result = {"type": "error", "code": "audio_provider_failure"}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
