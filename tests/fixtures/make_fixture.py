"""How `tts-fixture.mp3` was made. Not run by the tests and not a project dependency.

The clip is synthetic speech from espeak-ng (a text-to-speech program) reading a sentence written for this repository.
It is not Legislature audio and not a recording of a person. Regenerate (needs network once, to install):

    uv run --no-project --with espeakng-loader --with av python tests/fixtures/make_fixture.py tests/fixtures/tts-fixture.mp3
"""

from __future__ import annotations

import array
import ctypes
import sys
from fractions import Fraction

import av
import espeakng_loader

TEXT = "The committee will come to order. This is a test of the transcriber."
RATE = 22050


def synthesize(text: str) -> array.array:
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    samples = array.array("h")
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

    def collect(wav, count, _events):
        if wav and count > 0:
            samples.extend(wav[:count])
        return 0

    callback = callback_type(collect)
    lib.espeak_Initialize.restype = ctypes.c_int
    rate = lib.espeak_Initialize(2, 0, espeakng_loader.get_data_path().encode(), 0)  # synchronous, no playback
    if rate < 0:
        raise SystemExit("espeak_Initialize failed")
    lib.espeak_SetSynthCallback(callback)
    lib.espeak_SetVoiceByName(b"en-us")
    data = text.encode() + b"\0"
    lib.espeak_Synth(data, len(data), 0, 1, 0, 0x1, None, None)  # POS_CHARACTER, espeakCHARS_UTF8
    lib.espeak_Synchronize()
    global RATE
    RATE = rate
    return samples


def write_mp3(samples: array.array, path: str) -> None:
    with av.open(path, "w") as out:
        stream = out.add_stream("libmp3lame", rate=RATE)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(__import__("numpy").frombuffer(samples, dtype="int16").reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        frame.time_base = Fraction(1, RATE)
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


if __name__ == "__main__":
    write_mp3(synthesize(TEXT), sys.argv[1])
