from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uhip.phase0 import CameraAdapter
from uhip.phase0.mediapipe_camera import MediaPipeHandsClassifier, OpenCVCameraSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded local UHIP Phase 0 camera recognition smoke test."
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--device-id", default="mac-camera")
    parser.add_argument("--session-id", default=f"camera-{secrets.token_hex(6)}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = OpenCVCameraSource(
        camera_index=args.camera_index,
        max_frames=args.max_frames,
    )
    classifier = MediaPipeHandsClassifier()
    adapter = CameraAdapter(
        source=source,
        classifier=classifier,
        device_id=args.device_id,
        session_id=args.session_id,
        engine="mediapipe-hands-local",
        engine_version="1.1.0",
        model_sha256="mediapipe-hands-1.1.0",
    )

    accepted = 0
    rejected = 0
    try:
        for result in adapter.run():
            if result.passed:
                accepted += 1
                print(json.dumps(result.event, ensure_ascii=False, sort_keys=True))
            else:
                rejected += 1
                print(
                    json.dumps(
                        {"accepted": False, "reason": result.reason},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
    finally:
        classifier.close()

    print(
        json.dumps(
            {
                "summary": {
                    "accepted": accepted,
                    "rejected": rejected,
                    "max_frames": args.max_frames,
                    "network": False,
                    "os_actions": False,
                }
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
