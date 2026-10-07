from __future__ import annotations

import argparse
import json
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uhip.phase0 import CameraAdapter
from uhip.phase0.camera_adapter import CameraFrame, ClassifiedHand
from uhip.phase0.hand_position import HandPosition
from uhip.phase0.mediapipe_camera import MediaPipeHandsClassifier, OpenCVCameraSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded local UHIP Phase 0 camera recognition smoke test."
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=1,
        help="OpenCV camera index. On this Mac, 1 is the MacBook Pro camera; 0 is the iPhone.",
    )
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--device-id", default="mac-camera")
    parser.add_argument("--session-id", default=f"camera-{secrets.token_hex(6)}")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a local-only live preview with classification and gate status. "
        "Press q or Esc to stop.",
    )
    return parser.parse_args()


@dataclass
class PreviewCameraSource:
    """Store only the current in-memory frame for local display."""

    source: OpenCVCameraSource
    last_frame: CameraFrame | None = None

    def frames(self):
        for frame in self.source.frames():
            self.last_frame = frame
            yield frame


@dataclass
class PreviewClassifier:
    """Capture the latest local classifier result for the optional overlay."""

    classifier: MediaPipeHandsClassifier
    last_result: ClassifiedHand | None = None
    last_position: HandPosition | None = None

    def classify(self, frame: CameraFrame) -> ClassifiedHand:
        self.last_result = self.classifier.classify(frame)
        self.last_position = self.classifier.last_position
        return self.last_result


def preview_classifier_position(position: HandPosition | None) -> str:
    """Return a display-only normalized hand coordinate when available."""
    if position is None:
        return "unavailable"
    return f"({position.x:.3f},{position.y:.3f})"


def _draw_preview(
    cv2: object,
    frame: CameraFrame,
    classified: ClassifiedHand | None,
    hand_position: HandPosition | None,
    passed: bool,
    reason: str,
    camera_index: int,
) -> None:
    image = frame.data.copy()
    if classified is None:
        lines = [
            f"camera_index={camera_index}",
            "classifier=waiting",
        ]
    else:
        lines = [
            f"camera_index={camera_index}",
            f"hand_count={classified.hand_count}",
            f"gesture={classified.gesture}",
            f"hand_xy={preview_classifier_position(hand_position)}",
            f"confidence={classified.confidence_calibrated:.2f}",
            f"stable_frames={classified.stable_frames}",
            f"gate={'PASS' if passed else 'FAIL'}:{reason}",
        ]

    y = 28
    for line in lines:
        cv2.putText(
            image,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0) if passed else (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        y += 28

    cv2.imshow("UHIP Phase 0 - local camera", image)


def main() -> int:
    args = parse_args()
    source = PreviewCameraSource(
        OpenCVCameraSource(
            camera_index=args.camera_index,
            max_frames=args.max_frames,
        )
    )
    classifier = MediaPipeHandsClassifier()
    preview_classifier = PreviewClassifier(classifier)
    adapter = CameraAdapter(
        source=source,
        classifier=preview_classifier,
        device_id=args.device_id,
        session_id=args.session_id,
        engine="mediapipe-hands-local",
        engine_version="0.10.21",
        model_sha256="mediapipe-hands-0.10.21",
    )

    accepted = 0
    rejected = 0
    stopped_by_user = False
    try:
        import cv2

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

            if args.preview and source.last_frame is not None:
                _draw_preview(
                    cv2,
                    source.last_frame,
                    preview_classifier.last_result,
                    preview_classifier.last_position,
                    result.passed,
                    result.reason,
                    args.camera_index,
                )
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    stopped_by_user = True
                    break
    finally:
        classifier.close()
        if args.preview:
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:
                pass

    print(
        json.dumps(
            {
                "summary": {
                    "accepted": accepted,
                    "rejected": rejected,
                    "max_frames": args.max_frames,
                    "network": False,
                    "os_actions": False,
                    "preview": args.preview,
                    "stopped_by_user": stopped_by_user,
                }
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
