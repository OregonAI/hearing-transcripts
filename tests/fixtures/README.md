# Test fixture

`tts-fixture.mp3` is about 3.5 seconds of synthetic speech. It is not Legislature audio, not Invintus audio and not a
recording of a person. It is the only audio file allowed in the repository, and `.gitignore` names it.

## License

The clip and the sentence it reads are dedicated to the public domain under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) (owner decision, 2026-11-05):

> The committee will come to order. This is a test of the transcriber.

The sentence is original to this repository. This CC0 dedication covers `tts-fixture.mp3` and that sentence, and nothing
else in the repository (the rest is under the repository's `LICENSE`).

## How it was made

espeak-ng (a text-to-speech program) read the sentence above, and the result was encoded to MP3 (mono, 22.05 kHz).
`make_fixture.py` is the script, and the `TEXT` in it is the sentence. espeak-ng is GPL-licensed software; its license
covers the program, not the audio it produces, so the output carries no GPL obligation. No recording of a person and no
third-party text went into the clip.

The tests do not run `make_fixture.py`.
