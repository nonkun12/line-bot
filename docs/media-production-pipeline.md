# Original audiovisual production pipeline

The first production increment is music and video together. The eventual game is the long-term destination, but it grows from the audiovisual and interactive narrative foundations rather than replacing them.

## Local, free-only workflow

1. Create and review a `video-scenario.v1` scenario JSON.
2. Build a scenario-aware music cue plan and synchronized video EDL.
3. Generate an original editable MIDI sketch and a dependency-free 16-bit stereo WAV preview. The shared melodic motif stays recognizable while scene energy changes its register and dynamics.
4. Supply local scene clips or still images and assemble a draft MP4 with FFmpeg.
5. Optionally use a locally installed FluidSynth renderer and a user-supplied SF2/SF3 soundfont.

No paid API, cloud media service, or asset download is used.

## Create a bundle

```bash
python -m scripts.create_audiovisual_bundle scenario.json ./artifacts/short-film-01
```

The output directory must not already exist. It contains:

- `scenario.json` — structured story and scene timings
- `music_plan.json` — emotional arc, cues, sync points and mix intent
- `original_music.mid` — editable four-track MIDI
- `original_music.wav` — synthesized preview (first 90 seconds maximum)
- `edit_decision_list.json` — synchronized video/audio timeline
- `manifest.json` — artifact and render status

For longer works, the dependency-free preview is capped at 90 seconds to bound memory and CPU use. A full-length video render therefore requires a full-length local WAV through `--audio-path`, or a locally supplied soundfont through `--soundfont`.

## Assemble a draft MP4

Prepare a JSON object mapping every scene ID to an existing local media file:

```json
{
  "SC01": "./assets/scene-01.mp4",
  "SC02": "./assets/scene-02.png",
  "SC03": "./assets/scene-03.mp4"
}
```

Then run:

```bash
python -m scripts.create_audiovisual_bundle scenario.json ./artifacts/short-film-01 \
  --scene-media-json scene-assets.json --audio-path ./audio/full-mix.wav
```

FFmpeg is invoked with an argument list (not a shell), a timeout, local-only inputs, and a non-overwriting output path. The initial renderer uses sequential hard cuts; advanced transitions, generated visual assets, color grading, subtitles, mastering and final human review remain later production stages. Publishing or using third-party media requires a separate rights review.