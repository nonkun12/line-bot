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
from uhip.phase0.mediapipe_camera import MediaPipeHandsClassifier, OpenCVCameraSource


GESTURE_MEANINGS = {
    "open_palm": "open hand",
    "thumb_up": "thumb up",
    "fist": "closed fist",
    "swipe_left": "swipe left (not implemented)",
    "swipe_right": "swipe right (not implemented)",
    "pinch": "pinch (not implemented)",
    "unknown": "unknown / fail-closed",
}

GESTURE_MEANINGS_JA = {
    "open_palm": "open_palm = 手のひらを開く",
    "thumb_up": "thumb_up = 親指を立てる",
    "fist": "fist = 握りこぶし",
    "swipe_left": "swipe_left = 左へスワイプ（未実装）",
    "swipe_right": "swipe_right = 右へスワイプ（未実装）",
    "pinch": "pinch = 親指と人差し指をつまむ（未実装）",
}



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

    def classify(self, frame: CameraFrame) -> ClassifiedHand:
        self.last_result = self.classifier.classify(frame)
        return self.last_result


def _draw_preview(
    cv2: object,
    frame: CameraFrame,
    classified: ClassifiedHand | None,
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
            f"meaning={GESTURE_MEANINGS.get(classified.gesture, "不明")}",
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

    print("Gesture mapping:")
    for meaning in GESTURE_MEANINGS_JA.values():
        print(f"  - {meaning}")
    print("  - unknown = 認識できない／安全側で拒否")

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
