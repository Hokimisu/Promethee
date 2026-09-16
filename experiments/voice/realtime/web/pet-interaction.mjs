/** Pointer intentions only. The server owns every object and body transform. */
export function petSessionTransition(current, before, result = null) {
    if (!before || current.fence !== before.fence) return null;
    if (!result && current.session !== before.session) return null;
    const session = result ? result.session_id : before.session;
    const cursor = result ? result.cursor : current.cursor;
    if (
        typeof session !== "string" ||
        !session ||
        !Number.isSafeInteger(cursor) ||
        cursor < 0
    )
        throw new Error("Session de l’intervention invalide.");
    return {
        session,
        cursor,
        watching: before.watching,
        audioAllowed: before.audioAllowed,
    };
}

export function boundedPoint(point, bounds) {
    if (
        !Array.isArray(point) ||
        point.length !== 3 ||
        !point.every(Number.isFinite)
    )
        throw new Error("Position de dépôt invalide.");
    if (!bounds?.min || !bounds?.max)
        throw new Error("Limites de la boîte indisponibles.");
    return point.map((value, i) =>
        Math.max(bounds.min[i], Math.min(bounds.max[i], value)),
    );
}

export function throwVelocity(from, to) {
    const dx = to[0] - from[0],
        dz = to[2] - from[2];
    const distance = Math.hypot(dx, dz);
    if (distance < 0.025) return [0, 0, 0];
    const speed = Math.min(5, distance * 3);
    return [
        (dx / distance) * speed,
        Math.min(3, distance * 2),
        (dz / distance) * speed,
    ];
}

function receipt(result, id) {
    if (
        result?.request_id !== id ||
        result.status !== "applied" ||
        !Number.isSafeInteger(result.command_revision) ||
        result.command_revision < 0
    )
        throw new Error("L’intervention n’a pas été confirmée.");
    return result;
}

export class PetInteraction {
    constructor({
        request,
        current,
        onReply = () => true,
        onChange = () => {},
        onError = () => {},
        uuid = () => crypto.randomUUID(),
    }) {
        Object.assign(this, {
            request,
            current,
            onReply,
            onChange,
            onError,
            uuid,
        });
        this.operation = null;
        this.mode = "move";
        this.model = null;
        this.placement = "floor";
        this.pending = 0;
    }
    get busy() {
        return this.operation !== null || this.pending > 0;
    }
    available(kind) {
        const state = this.current();
        return Boolean(
            state.ready &&
            state.catalog?.supported_interventions?.includes(kind),
        );
    }
    selectModel(model) {
        if (
            this.busy ||
            !this.available("spawn") ||
            !this.current().catalog.object_models.includes(model)
        )
            return false;
        this.model = model;
        this.placement = "floor";
        this.onChange();
        return true;
    }
    setPlacement(placement) {
        if (
            this.busy ||
            this.model !== "plush" ||
            !["floor", "high"].includes(placement)
        )
            return false;
        this.placement = placement;
        this.onChange();
        return true;
    }
    setMode(mode) {
        if (this.busy || !["move", "throw"].includes(mode)) return false;
        if (mode === "throw" && !this.available("throw")) return false;
        this.model = null;
        this.mode = mode;
        this.onChange();
        return true;
    }
    guard() {
        const revision = this.current().revision;
        if (!Number.isSafeInteger(revision) || revision < 0)
            throw new Error("Attendez l’état confirmé de la boîte.");
        return revision;
    }
    async send(
        kind,
        args,
        revision,
        id = "pet-" + this.uuid(),
        cleanup = false,
    ) {
        this.pending++;
        this.onChange();
        try {
            const result = receipt(
                await this.request(
                    "/pet",
                    {
                        request_id: id,
                        expected_command_revision: revision,
                        action: { kind, args },
                    },
                    { cleanup },
                ),
                id,
            );
            const current = cleanup ? false : this.onReply(result);
            return { result, current };
        } finally {
            this.pending--;
            this.onChange();
        }
    }
    async spawn(point) {
        if (!this.model || this.busy || !this.available("spawn")) return false;
        const model = this.model;
        this.model = null;
        try {
            const { current } = await this.send(
                "spawn",
                {
                    model,
                    position: boundedPoint(
                        point,
                        this.current().catalog.bounds,
                    ),
                },
                this.guard(),
            );
            return current;
        } catch (error) {
            this.onError(error);
            return false;
        } finally {
            this.onChange();
        }
    }
    async begin(target, point) {
        if (
            this.busy ||
            !this.available("grab_begin") ||
            !this.available("grab_end") ||
            !this.available("grab_cancel")
        )
            return false;
        if (
            this.mode === "throw" &&
            (target.kind !== "object" || target.asset !== "ball")
        )
            return false;
        const id = "pet-" + this.uuid();
        const operation = {
            id,
            target: { ...target },
            origin: [...point],
            point: [...point],
            mode: this.mode,
            phase: "acquiring",
            released: false,
            receipt: null,
        };
        this.operation = operation;
        this.onChange();
        try {
            const args = { target: target.kind };
            if (target.kind === "object") args.object_id = target.id;
            const { result, current } = await this.send(
                "grab_begin",
                args,
                this.guard(),
                id,
            );
            if (result.grab_id !== id)
                throw new Error("La saisie n’a pas été confirmée.");
            operation.receipt = result;
            if (this.operation !== operation || !current) {
                if (this.operation === operation) this.operation = null;
                await this.releaseCancelled(operation);
                return false;
            }
            operation.phase = "dragging";
            this.onChange();
            if (operation.released) return this.finish(operation);
            return true;
        } catch (error) {
            if (this.operation === operation) {
                this.operation = null;
                this.onError(error);
            }
            return false;
        } finally {
            this.onChange();
        }
    }
    move(point) {
        const operation = this.operation;
        if (!operation || operation.phase === "committing") return;
        operation.point = boundedPoint(point, this.current().catalog.bounds);
        this.onChange();
    }
    async release() {
        const operation = this.operation;
        if (!operation || operation.phase === "committing") return false;
        operation.released = true;
        if (!operation.receipt) return false; // Wait for begin acknowledgement, never guess its guard.
        return this.finish(operation);
    }
    async finish(operation) {
        if (this.operation !== operation || !operation.receipt) return false;
        operation.phase = "committing";
        this.onChange();
        const point =
            operation.mode === "throw" ? operation.origin : operation.point;
        const args = {
            grab_id: operation.id,
            position:
                operation.target.kind === "avatar"
                    ? [point[0], point[2]]
                    : [...point],
        };
        if (operation.mode === "throw")
            args.velocity = throwVelocity(operation.origin, operation.point);
        try {
            const { current } = await this.send(
                "grab_end",
                args,
                operation.receipt.command_revision,
            );
            return current && this.operation === operation;
        } catch (error) {
            if (this.operation === operation) this.onError(error);
            await this.releaseCancelled(operation);
            return false;
        } finally {
            if (this.operation === operation) this.operation = null;
            this.onChange();
        }
    }
    async releaseCancelled(operation) {
        if (!operation.receipt || operation.cancelSent) return;
        operation.cancelSent = true;
        try {
            await this.send(
                "grab_cancel",
                { grab_id: operation.id },
                operation.receipt.command_revision,
                "pet-" + this.uuid(),
                true,
            );
        } catch (error) {
            this.onError(new Error(`Saisie à vérifier : ${error.message}`));
        }
    }
    cancel() {
        this.model = null;
        const operation = this.operation;
        this.operation = null;
        this.onChange();
        // A late begin acknowledgement will release its own immutable grab ID.
        return operation ? this.releaseCancelled(operation) : Promise.resolve();
    }
}
