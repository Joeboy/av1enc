#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


GPU_ENCODER_PREFERENCE = ("av1_nvenc", "av1_qsv", "av1_amf", "av1_vaapi")

DEBUG = False


def debug(msg: str) -> None:
    if DEBUG:
        print(msg, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="av1enc",
        description="Convert videos to AV1 with sensible defaults for web embedding.",
    )
    parser.add_argument("input", type=Path, help="Input video file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file path (defaults to <input_stem>.av1.webm)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files without prompting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg command without executing it",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg binary (default: ffmpeg)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show diagnostic output (encoder probing, ffmpeg command details)",
    )
    parser.add_argument(
        "--resize",
        help=(
            "Resize as WIDTHxHEIGHT, WIDTHx, or xHEIGHT "
            "(examples: 1920x1080, 1080x, x720). "
            "Default is x720; use --resize=false to disable resizing"
        ),
    )
    return parser


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.av1.webm")


def parse_size_arg(size: str) -> str:
    if "x" in size and not size.startswith("x") and not size.endswith("x"):
        width_str, height_str = size.split("x", 1)
        if width_str.isdigit() and height_str.isdigit():
            width = int(width_str)
            height = int(height_str)
            if width <= 0 or height <= 0:
                raise ValueError("Width and height must be positive integers")
            return f"scale={width}:{height}"

    if size.startswith("x") and size[1:].isdigit():
        height = int(size[1:])
        if height <= 0:
            raise ValueError("Height must be a positive integer")
        return f"scale=-2:{height}"

    if size.endswith("x") and size[:-1].isdigit():
        width = int(size[:-1])
        if width <= 0:
            raise ValueError("Width must be a positive integer")
        return f"scale={width}:-2"

    raise ValueError(
        "Invalid resize format. Use WIDTHxHEIGHT, WIDTHx, or xHEIGHT (examples: 1920x1080, 1080x, x720)"
    )


def confirm_overwrite(output_path: Path) -> bool:
    prompt = f"Output file exists: {output_path}\nOverwrite? [y/N]: "
    while True:
        response = input(prompt).strip().lower()
        if response in {"y", "yes"}:
            return True
        if response in {"", "n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def detect_available_av1_encoders(ffmpeg_bin: str) -> set[str]:
    result = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"

    candidates = {"libsvtav1", *GPU_ENCODER_PREFERENCE}
    return {
        encoder
        for encoder in candidates
        if f" {encoder}" in output or f" {encoder}\n" in output
    }


def is_encoder_runtime_usable(ffmpeg_bin: str, video_encoder: str) -> bool:
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        *build_video_preamble_args(video_encoder),
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=128x72:r=1",
        "-frames:v",
        "1",
        *build_video_encoder_args(video_encoder),
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout + result.stderr).strip()
    if output:
        debug(output)
    return result.returncode == 0


def select_runtime_video_encoder(ffmpeg_bin: str, available_encoders: set[str]) -> str:
    debug(f"Available AV1 encoders in ffmpeg build: {', '.join(available_encoders)}")
    for encoder in GPU_ENCODER_PREFERENCE:
        if encoder not in available_encoders:
            continue
        debug(f"Probing GPU encoder: {encoder}")
        if is_encoder_runtime_usable(ffmpeg_bin, encoder):
            debug(f"GPU encoder available: {encoder}")
            return encoder
        debug(f"GPU encoder unusable at runtime: {encoder}")
    return "libsvtav1"


def build_video_preamble_args(video_encoder: str) -> list[str]:
    """Global options that must appear before the input for this encoder."""
    if video_encoder == "av1_qsv":
        return ["-init_hw_device", "qsv=hw"]
    if video_encoder == "av1_vaapi":
        return ["-init_hw_device", "vaapi=hw", "-filter_hw_device", "hw"]
    return []


def build_video_encoder_args(
    video_encoder: str, scale_filter: str | None = None
) -> list[str]:
    maybe_scale = ["-vf", scale_filter] if scale_filter else []

    if video_encoder == "av1_nvenc":
        return [
            *maybe_scale,
            "-c:v",
            "av1_nvenc",
            "-preset",
            "p5",
            "-rc",
            "vbr",
            "-cq",
            "30",
            "-b:v",
            "0",
            "-g",
            "240",
        ]

    if video_encoder == "av1_qsv":
        return [
            *maybe_scale,
            "-c:v",
            "av1_qsv",
            "-preset",
            "medium",
            "-global_quality:v",
            "28",
            "-g",
            "240",
        ]

    if video_encoder == "av1_amf":
        return [
            *maybe_scale,
            "-c:v",
            "av1_amf",
            "-quality",
            "balanced",
            "-g",
            "240",
        ]

    if video_encoder == "av1_vaapi":
        vaapi_filter = "format=nv12,hwupload"
        if scale_filter:
            vaapi_filter = f"{scale_filter},{vaapi_filter}"
        return [
            "-vf",
            vaapi_filter,
            "-c:v",
            "av1_vaapi",
            "-qp",
            "30",
            "-g",
            "240",
        ]

    return [
        *maybe_scale,
        "-c:v",
        "libsvtav1",
        "-preset",
        "6",
        "-crf",
        "32",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "240",
        "-svtav1-params",
        "tune=0",
    ]


def build_ffmpeg_command(
    ffmpeg_bin: str,
    input_path: Path,
    output_path: Path,
    overwrite: bool,
    video_encoder: str,
    scale_filter: str | None,
) -> list[str]:
    overwrite_flag = "-y" if overwrite else "-n"
    video_args = build_video_encoder_args(video_encoder, scale_filter=scale_filter)

    return [
        ffmpeg_bin,
        "-hide_banner",
        *build_video_preamble_args(video_encoder),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *video_args,
        "-c:a",
        "libopus",
        "-b:a:0",
        "96k",
        "-ac",
        "2",
        "-ar",
        "48000",
        overwrite_flag,
        str(output_path),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = args.input.expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        parser.error(f"Input file does not exist: {input_path}")

    ffmpeg_path = shutil.which(args.ffmpeg_bin)
    if ffmpeg_path is None:
        parser.error(f"ffmpeg binary not found: {args.ffmpeg_bin}")

    available_encoders = detect_available_av1_encoders(ffmpeg_path)
    if "libsvtav1" not in available_encoders and not any(
        encoder in available_encoders for encoder in GPU_ENCODER_PREFERENCE
    ):
        parser.error("No supported AV1 encoder found in ffmpeg build")

    global DEBUG
    DEBUG = args.debug

    selected_encoder = select_runtime_video_encoder(ffmpeg_path, available_encoders)

    scale_filter: str | None = None
    if args.resize is None:
        scale_filter = "scale=-2:720"
    elif args.resize.lower() in {"false", "off", "none", "0"}:
        scale_filter = None
    else:
        try:
            scale_filter = parse_size_arg(args.resize)
        except ValueError as exc:
            parser.error(str(exc))

    output_path = (
        (args.output or default_output_path(input_path)).expanduser().resolve()
    )
    if output_path.exists() and not args.overwrite:
        if not sys.stdin.isatty():
            parser.error(
                f"Output file already exists: {output_path}. Use --overwrite to replace it"
            )
        if not confirm_overwrite(output_path):
            raise SystemExit("Cancelled by user")
        args.overwrite = True

    command = build_ffmpeg_command(
        ffmpeg_bin=ffmpeg_path,
        input_path=input_path,
        output_path=output_path,
        overwrite=args.overwrite,
        video_encoder=selected_encoder,
        scale_filter=scale_filter,
    )

    print(f"Using AV1 encoder: {selected_encoder}")

    if args.dry_run:
        print(" ".join(command))
        return

    try:
        subprocess.run(command, check=True)
        return
    except subprocess.CalledProcessError as exc:
        if selected_encoder != "libsvtav1" and "libsvtav1" in available_encoders:
            debug("GPU AV1 encoding failed; falling back to CPU encoder: libsvtav1")
            # A failed GPU run can leave a partial file behind.
            if output_path.exists() and not args.overwrite:
                output_path.unlink()
            fallback_command = build_ffmpeg_command(
                ffmpeg_bin=ffmpeg_path,
                input_path=input_path,
                output_path=output_path,
                overwrite=args.overwrite,
                video_encoder="libsvtav1",
                scale_filter=scale_filter,
            )
            subprocess.run(fallback_command, check=True)
            return
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
