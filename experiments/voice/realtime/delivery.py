"""Astra chooses words and performance together; only words enter the TTS text."""

import json

from dialogue import MAX_DELIVERY_CHARS, MAX_TEXT_CHARS, MAX_WORDS, word_count
from speech_text import prepare_speech_text


def parse_delivery(raw):
    if not isinstance(raw, str) or len(raw) > 2400:
        raise ValueError("Réponse vocale structurée trop longue.")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"text", "delivery"}:
        raise ValueError("La réponse doit contenir text et delivery.")
    for field, limit in (("text", MAX_TEXT_CHARS), ("delivery", MAX_DELIVERY_CHARS)):
        if not isinstance(value[field], str) or not 1 <= len(value[field].strip()) <= limit:
            raise ValueError("Champ vocal invalide : " + field)
    speech = prepare_speech_text(value["text"], value["delivery"])
    if any(char in speech["spoken_text"] for char in "()（）"):
        raise ValueError("Les directions de jeu doivent rester dans delivery.")
    if word_count(speech["display_text"]) > MAX_WORDS:
        raise ValueError("Réplique trop longue pour une conversation spontanée.")
    if len(speech["nonverbal_tags"]) > 1:
        raise ValueError("Une seule balise vocale au maximum par réplique.")
    return {"text": speech["spoken_text"], "delivery": speech["style"]}


class DirectedWorker:
    """Keep native Hermes history verbatim, persist the actual spoken text separately."""

    def __init__(self, worker, turn_id, deliveries):
        self.worker, self.turn_id, self.deliveries = worker, turn_id, deliveries

    def poll(self):
        result = self.worker.poll()
        if (
            not result
            or result.get("type") != "result"
            or result.get("failed")
            or result.get("interrupted")
        ):
            return result
        if result.get("turn_id") != self.turn_id:
            return result  # The existing host validates and rejects a mismatched result.
        try:
            directed = parse_delivery(result.get("text"))
        except (ValueError, TypeError):
            return {"type": "error", "code": "invalid_vocal_direction"}
        self.deliveries[self.turn_id] = directed["delivery"]
        return {**result, "text": directed["text"]}

    def close(self):
        return self.worker.close()
