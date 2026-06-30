#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path


SAMPLE_RATE = 44_100
NOTE_INDEX = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def note_frequency(name: str) -> float:
    pitch = name[:-1]
    octave = int(name[-1])
    midi = 12 * (octave + 1) + NOTE_INDEX[pitch]
    return 440.0 * (2 ** ((midi - 69) / 12))


def add_note(
    buffer: list[float],
    start: float,
    duration: float,
    note: str,
    velocity: float,
    *,
    pan: float = 0.0,
) -> None:
    freq = note_frequency(note)
    start_i = max(0, int(start * SAMPLE_RATE))
    end_i = min(len(buffer) // 2, int((start + duration) * SAMPLE_RATE))
    if start_i >= len(buffer) // 2 or end_i <= start_i:
        return
    total = max(1, end_i - start_i)
    left_gain = math.cos((pan + 1) * math.pi / 4)
    right_gain = math.sin((pan + 1) * math.pi / 4)

    for i in range(total):
        t = i / SAMPLE_RATE
        pos = i / total
        attack = min(1.0, pos / 0.08)
        decay = 1.0 - max(0.0, min(1.0, (pos - 0.12) / 0.88)) * 0.68
        release = min(1.0, (1.0 - pos) / 0.18)
        envelope = attack * decay * release
        # Soft piano-like additive tone. This is generated audio, not a recording.
        tone = (
            math.sin(2 * math.pi * freq * t)
            + 0.34 * math.sin(2 * math.pi * freq * 2.01 * t)
            + 0.16 * math.sin(2 * math.pi * freq * 3.02 * t)
            + 0.07 * math.sin(2 * math.pi * freq * 4.02 * t)
        )
        tone *= velocity * envelope
        idx = (start_i + i) * 2
        buffer[idx] += tone * left_gain
        buffer[idx + 1] += tone * right_gain


def render(duration: float, output: Path) -> None:
    buffer = [0.0] * (int(duration * SAMPLE_RATE) * 2)
    bpm = 72
    beat = 60 / bpm
    bar = beat * 3

    progression = [
        ("C3", "Eb3", "G3", "C4"),
        ("Ab2", "C3", "Eb3", "Ab3"),
        ("Bb2", "D3", "F3", "Bb3"),
        ("G2", "B2", "D3", "G3"),
        ("C3", "Eb3", "G3", "C4"),
        ("F2", "Ab2", "C3", "F3"),
        ("G2", "B2", "D3", "G3"),
        ("C3", "Eb3", "G3", "C4"),
    ]
    melody = [
        "G4",
        "Bb4",
        "C5",
        "D5",
        "Eb5",
        "D5",
        "C5",
        "Bb4",
        "G4",
        "Eb4",
        "F4",
        "G4",
        "C5",
        "Bb4",
        "Ab4",
        "G4",
    ]

    bars = int(math.ceil(duration / bar)) + 1
    for n in range(bars):
        start = n * bar
        chord = progression[n % len(progression)]
        root, third, fifth, high = chord
        add_note(buffer, start, beat * 2.85, root, 0.085, pan=-0.28)
        add_note(buffer, start + beat, beat * 0.95, third, 0.055, pan=-0.18)
        add_note(buffer, start + beat * 2, beat * 0.95, fifth, 0.055, pan=-0.18)
        add_note(buffer, start + beat * 2.48, beat * 0.5, high, 0.04, pan=-0.12)

        if n % 2 == 0:
            note = melody[(n // 2) % len(melody)]
            add_note(buffer, start + beat * 0.22, beat * 1.55, note, 0.07, pan=0.16)
            add_note(buffer, start + beat * 1.95, beat * 0.82, melody[(n // 2 + 3) % len(melody)], 0.045, pan=0.18)
        else:
            add_note(buffer, start + beat * 0.35, beat * 1.1, melody[(n // 2 + 5) % len(melody)], 0.052, pan=0.18)

    peak = max(0.01, max(abs(sample) for sample in buffer))
    scale = 0.42 / peak
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for sample in buffer:
            val = int(max(-1.0, min(1.0, sample * scale)) * 32767)
            wav.writeframesraw(val.to_bytes(2, "little", signed=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a soft Chopin-inspired piano bed.")
    parser.add_argument("--duration", type=float, default=161.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo-video/chopin_style_bgm.wav"))
    args = parser.parse_args()
    render(args.duration, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
