// Amplitude-driven jaw opening, not phonetic lip sync. Only rendered PCM owns it.
export class AudioMouth {
    constructor(manager) {
        this.manager = manager;
        this.expression =
            ["aa", "oh"].find((name) => manager?.getExpression(name)) ?? null;
        this.value = 0;
    }
    update(rms, dt) {
        const level = Number.isFinite(rms) ? Math.max(0, rms) : 0;
        // A soft curve makes quiet speech visible without animating digital silence.
        const target = Math.min(
            0.9,
            0.9 * Math.sqrt(Math.max(0, level - 0.002) / 0.12),
        );
        const rate = target > this.value ? 30 : 24;
        this.value +=
            (target - this.value) *
            (1 - Math.exp(-Math.max(0, Math.min(dt, 0.1)) * rate));
        if (target === 0 && this.value < 0.002) this.value = 0;
        this.apply();
        return this.value;
    }
    apply() {
        if (this.expression) this.manager.setValue(this.expression, this.value);
    }
    reset() {
        this.value = 0;
        this.apply();
    }
}
