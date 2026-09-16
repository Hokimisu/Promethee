export function consumeEvents(batch, session, cursor, accept) {
    if (batch.session_id !== session) return cursor;
    if (!Array.isArray(batch.events) || !Number.isSafeInteger(batch.cursor)) {
        throw new Error("Flux audio invalide.");
    }
    if (batch.gap) {
        throw new Error(
            "La connexion a perdu une partie du son. Redémarrez l’essai.",
        );
    }
    for (const event of batch.events) {
        if (!Number.isSafeInteger(event.cursor))
            throw new Error("Curseur audio invalide.");
        if (event.cursor <= cursor) continue;
        if (event.session_id === session) accept(event);
        cursor = event.cursor;
    }
    return Math.max(cursor, batch.cursor);
}
