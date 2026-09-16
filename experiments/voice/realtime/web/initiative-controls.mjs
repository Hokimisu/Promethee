export function initiativeButtonState(initiative, audioAllowed) {
    if (!initiative) return { label: "Activer", paused: null };
    if (!initiative.paused && !audioAllowed)
        return { label: "Activer la voix", paused: false };
    return {
        label: initiative.paused ? "Reprendre" : "Mettre en pause",
        paused: !initiative.paused,
    };
}

export function initiativeConfiguration(budget, interval) {
    if (!Number.isSafeInteger(budget) || budget < 1 || budget > 1000)
        throw new Error("Choisissez un budget entier de 1 à 1 000 appels.");
    if (
        interval !== null &&
        (typeof interval !== "number" ||
            !Number.isFinite(interval) ||
            interval < 1)
    )
        throw new Error(
            "La cadence doit être d’au moins une seconde, ou rester vide.",
        );
    return { budget, interval };
}

export function initiativeTransition(current, result, enableAudio) {
    const initiative = result?.initiative;
    if (
        !initiative ||
        typeof initiative !== "object" ||
        !Number.isSafeInteger(initiative.remaining) ||
        initiative.remaining < 0 ||
        !Number.isSafeInteger(initiative.used) ||
        initiative.used < 0 ||
        typeof initiative.paused !== "boolean" ||
        (initiative.interval !== null &&
            (typeof initiative.interval !== "number" ||
                !Number.isFinite(initiative.interval) ||
                initiative.interval < 1)) ||
        typeof result.session_id !== "string" ||
        !result.session_id ||
        !Number.isSafeInteger(result.cursor) ||
        result.cursor < 0 ||
        typeof result.interrupted !== "boolean"
    )
        throw new Error("Réponse d’initiative invalide.");
    const changed = result.session_id !== current.session;
    return {
        initiative,
        session: result.session_id,
        cursor: changed ? result.cursor : current.cursor,
        resetAudio: changed,
        interrupted: result.interrupted,
        audioAllowed: enableAudio || current.audioAllowed,
        enableAudio,
    };
}

/** The initiative request has its own pending flag; it never stalls body polling. */
export class InitiativeControls {
    constructor({
        request,
        enableAudio,
        current,
        apply,
        onChange = () => {},
        onError = () => {},
    }) {
        Object.assign(this, {
            request,
            enableAudio,
            current,
            apply,
            onChange,
            onError,
        });
        this.pending = false;
    }
    configure(budget, interval) {
        return this.send(
            "/initiative_configure",
            initiativeConfiguration(budget, interval),
            true,
        );
    }
    pause(paused) {
        if (typeof paused !== "boolean")
            throw new Error("La pause doit être un booléen.");
        return this.send("/initiative_pause", { paused }, !paused);
    }
    async send(path, body, enableAudio) {
        if (this.pending) return false;
        const epoch = this.current().fence;
        this.pending = true;
        this.onChange();
        try {
            if (enableAudio) await this.enableAudio();
            if (epoch !== this.current().fence) return false;
            const result = await this.request(path, body);
            if (epoch !== this.current().fence) return false;
            this.apply(
                initiativeTransition(this.current(), result, enableAudio),
            );
            return true;
        } catch (error) {
            if (epoch === this.current().fence) this.onError(error);
            return false;
        } finally {
            this.pending = false;
            this.onChange();
        }
    }
}

export function shouldSendClientStats({
    session,
    audioAllowed,
    active,
    initiative,
}) {
    return Boolean(
        session &&
        audioAllowed &&
        (active || (initiative && !initiative.paused)),
    );
}

export function handleSessionStop(
    event,
    { disableMicrophone, stopLocal, resumeEvents = () => {}, onStopped },
) {
    if (event.event !== "stop" || event.id) return false;
    const stopBody = event.body !== false;
    if (stopBody) disableMicrophone();
    stopLocal(stopBody);
    if (!stopBody) resumeEvents();
    onStopped();
    return true;
}
