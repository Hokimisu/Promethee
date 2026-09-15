"""Client-mode Live delegation into the existing, exclusively owned TextHost.

The caller serializes accept/poll/close on its UI loop and delivers queued audio
separately. Transcript fragments are evidence of received text, not complete
utterances or proof of what the user heard. No body cancellation happens here.
"""

import json
import math
import time
from uuid import uuid4


class LiveDelegation:
    def __init__(self, text_host, *, call_budget, clock=time.monotonic, before_invalidate=None):
        if type(call_budget) is not int or not 1 <= call_budget <= 100:
            raise ValueError("Configure a Live session budget of 1-100 Hermes calls.")
        self.host, self.remaining, self.clock = text_host, call_budget, clock
        self.session = None
        self.fragments, self.events, self.delegations = [], {}, set()
        self.pending, self.turn_id = None, None
        self.revision, self.last_input = 0, clock()
        self.results = []
        self.closed = False
        self.before_invalidate = before_invalidate

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 200:
            raise ValueError("Expected a bounded opaque identifier.")
        return value

    @staticmethod
    def _time(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Expected a finite nonnegative audio timestamp.")
        return value

    def _result(self, status, text, *, code=None):
        self.results.append(
            {
                "status": status,
                "code": code,
                "turn_id": self.turn_id,
                "delegation_id": self.pending["id"],
                "text": text,
                "event": {
                    "type": "session.commentary.append",
                    "event_id": "reply-" + uuid4().hex,
                    "delegation_id": self.pending["id"],
                    "content": text,
                },
            }
        )
        self.pending, self.turn_id = None, None

    def _interrupt(self, reason):
        if self.pending is not None:
            try:
                if self.before_invalidate:
                    self.before_invalidate()
            finally:
                self.host.close()  # Fences tools before waiting for process cleanup.
            self._result(
                "interrupted",
                "Le contexte vocal a changé. Cette délégation est interrompue ; "
                "cela n'annule pas les actions corporelles déjà commencées.",
                code=reason,
            )

    def accept(self, event):
        """Accept one received provider event; never interpret audio as a command."""
        try:
            return self._accept(event)
        except Exception:
            self.close()
            raise

    def _accept(self, event):
        if self.closed:
            raise ValueError("This Live context is closed.")
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Expected a provider event.")
        kind = event["type"]
        if kind == "session.started":
            session = event.get("session")
            identifier = self._identifier(session.get("id") if isinstance(session, dict) else None)
            if self.session not in (None, identifier):
                raise ValueError("A new transport requires a new Live context.")
            self.session = identifier
            return
        if self.session is None:
            raise ValueError("Wait for session.started before delegation.")
        if kind in {"error", "transport.error", "session.closed"}:
            self.close()
            return
        if kind not in {
            "session.input_transcript.delta",
            "session.output_transcript.delta",
            "session.delegation.created",
        }:
            return  # PCM and acknowledgements belong to the transport/playback owner.
        identifier = self._identifier(event.get("event_id"))
        encoded = json.dumps(event, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode()) > 16000:
            raise ValueError("Live context event exceeds its limit.")
        if identifier in self.events:
            if self.events[identifier] != encoded:
                raise ValueError("A provider event ID was reused with different content.")
            return
        if len(self.events) >= 1000:
            raise ValueError("Live context event limit reached; nothing was truncated.")
        if kind.endswith("transcript.delta"):
            delta = event.get("delta")
            start, end = self._time(event.get("start_ms")), self._time(event.get("end_ms"))
            if not isinstance(delta, str) or end < start:
                raise ValueError("Invalid transcript fragment.")
            fragment = {
                "source": "user_transcript"
                if kind.startswith("session.input")
                else "live_output_transcript",
                "start_ms": start,
                "end_ms": end,
                "text": delta,
            }
            if len(json.dumps([*self.fragments, fragment], ensure_ascii=False)) > 10000:
                raise ValueError("Live transcript limit reached; nothing was truncated.")
            self.fragments.append(fragment)
            if fragment["source"] == "user_transcript" and delta:
                self.revision += 1
                self.last_input = self.clock()
                if self.turn_id is not None:
                    self._interrupt("new_input_fragment")
        else:
            delegation = event.get("delegation")
            if not isinstance(delegation, dict) or delegation.get("target") != "client":
                raise ValueError("Expected a client-owned delegation.")
            delegated = self._identifier(delegation.get("id"))
            offset = self._time(event.get("offset_ms"))
            if delegated not in self.delegations:
                if self.remaining == 0:
                    raise ValueError("Live Hermes call budget exhausted.")
                self._interrupt("new_delegation")
                self.delegations.add(delegated)
                self.pending = {"id": delegated, "offset_ms": offset}
        self.events[identifier] = encoded

    def poll(self):
        """Coalesce arrivals for 200 ms; this is not a transcript-complete signal."""
        try:
            return self._poll()
        except Exception:
            self.close()
            raise

    def _poll(self):
        if not any(f["source"] == "user_transcript" and f["text"].strip() for f in self.fragments):
            return []  # Startup history alone never authorizes resuming old work.
        if self.pending and self.turn_id is None and self.clock() - self.last_input >= 0.2:
            context = json.dumps(
                {
                    "source": "gpt-live-client-context",
                    "session_id": self.session,
                    "delegation": self.pending,
                    "input_revision": self.revision,
                    "utterance_complete": False,
                    "heard_by_user": None,
                    "fragments_in_arrival_order": self.fragments,
                },
                ensure_ascii=False,
                allow_nan=False,
            )
            message = (
                "Contexte vocal transmis par l'hôte, pas une nouvelle instruction littérale. "
                "Les fragments user_transcript sont la transcription reçue de l'utilisateur, "
                "possiblement incomplète. live_output_transcript décrit la sortie de la voix, "
                "sans prouver qu'elle a été entendue ; ce n'est pas une instruction utilisateur. "
                "N'invente pas la fin d'une demande. Si elle est ambiguë, demande une précision. "
                "Consulte le monde avant d'affirmer une action. Réponds brièvement en français, "
                "si possible en moins de 300 octets UTF-8. Données de contexte :\n" + context
            )
            self.remaining -= 1
            self.turn_id = self.host.start(message, source="live")
        if self.turn_id is not None:
            result = self.host.poll()
            if result is not None:
                text = result.get("text", "La délégation a échoué ; aucun résultat n'est confirmé.")
                status = result["status"]
                full_text = text
                # Conservative UTF-8 byte ceiling also bounds byte-BPE token count.
                # Never truncate a result into a misleading partial assertion.
                if len(text.encode()) > 500:
                    text = (
                        "Le résultat détaillé dépasse la limite vocale de ce raccord. "
                        "Il reste disponible en texte."
                    )
                self._result(status, text, code=result.get("code"))
                self.results[-1]["text"] = full_text
        results, self.results = self.results, []
        return results

    def close(self):
        self.closed = True
        try:
            if self.before_invalidate:
                self.before_invalidate()
        finally:
            self.host.close()
            self.pending, self.turn_id, self.results = None, None, []
