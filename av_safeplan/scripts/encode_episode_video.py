#!/usr/bin/env python3
"""Encode a saved RGB frame sequence as a small review video."""

import argparse
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path, help="Directory containing frame_*.png")
    parser.add_argument("output", type=Path, help="Output MP4 path")
    parser.add_argument("--fps", type=float, default=20.0)
    args = parser.parse_args()

    frames = sorted(args.frames.glob("frame_*.png"))
    if not frames:
        parser.error("no trajectory frames found in {}".format(args.frames))
    if args.fps <= 0:
        parser.error("fps must be positive")
    if args.output.exists():
        parser.error("output already exists: {}".format(args.output))

    first = cv2.imread(str(frames[0]))
    if first is None:
        raise ValueError("cannot read {}".format(frames[0]))
    height, width = first.shape[:2]
    writer = cv2.VideoWriter(
        str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError("MP4 encoder could not open {}".format(args.output))
    try:
        for path in frames:
            image = cv2.imread(str(path))
            if image is None or image.shape[:2] != (height, width):
                raise ValueError("unreadable or mismatched frame: {}".format(path))
            writer.write(image)
    finally:
        writer.release()

    print("Encoded {} frames at {} fps: {}".format(len(frames), args.fps, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
