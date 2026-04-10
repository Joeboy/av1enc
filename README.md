# av1enc

Little python script for converting videos to AV1 (video) + Opus (audio) format, using your installed ffmpeg. Output files should be suitable for embedding on the web. Hopefully has sensible defaults so you don't have to think much, and lets you override the things you might want to. In theory it should use GPU if available, but it turns out my RTX3060 is too old and puny for AV1 encoding so I haven't been able to test that.

## Requirements

- Python 3.11+
- `ffmpeg` with support for `libopus` plus at least one working AV1 encoder (`libsvtav1` is the fallback CPU-based option)

## Usage

```bash
av1enc input.mp4  # Convert input.mp4 to input.av1.webm
av1enc input.mp4 -o output.webm
av1enc input.mp4 --overwrite
av1enc input.mp4 --dry-run
av1enc input.mp4 --resize 1920x1080
av1enc input.mp4 --resize 1920x  # Calculates height automatically
av1enc input.mp4 --resize=false
av1enc input.mp4 --quality high
```

By default, output is written to `<input_stem>.av1.webm` next to the source file.

Use `--overwrite` to replace existing output without prompting.

By default, video is resized to `x720` (height 720, width auto-calculated).
Use `--resize` to scale video as `WIDTHxHEIGHT`, `WIDTHx`, or `xHEIGHT`.
Use `--resize=false` to disable resizing.

By default, quality profile is `standard`.
Use `--quality high` for fewer compression artifacts (slower encoding, larger files).

## Current default encoding profile

- Video codec: auto-selected AV1 encoder
  - `av1_nvenc`, `av1_qsv`, `av1_amf`, `av1_vaapi`, fallback to `libsvtav1`
  - `standard` profile uses balanced quality/speed defaults
  - `high` profile uses lower CQ/CRF (and slightly slower settings where available)
- Audio codec: `libopus`
- Audio bitrate: `96k`
- Audio channels/rate: stereo, `48kHz`
