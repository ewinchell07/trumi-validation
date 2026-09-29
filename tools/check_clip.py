#!/usr/bin/env python3
"""Quick sanity check for raw TRumi GoPro clips (run before a full session).

Usage: ~/trumi/.venv/bin/python ~/trumi_tools/check_clip.py CLIP.MP4 [CLIP2.MP4 ...]

Checks camera model/firmware/settings, IMU telemetry, and ArUco tag visibility
(finger tags 0/1 or 6/7, mapping tag 13) using the pipeline's own mirror mask.
"""
import collections
import json
import pathlib
import subprocess
import sys

import av
import cv2

sys.path.insert(0, str(pathlib.Path.home() / "trumi" / "src"))
from trumi.utils.cv_util import draw_predefined_mask  # noqa: E402
from py_gpmf_parser.gopro_telemetry_extractor import GoProTelemetryExtractor  # noqa: E402

TAG_NAMES = {0: "G0 left finger", 1: "G0 right finger", 6: "G1 left finger",
             7: "G1 right finger", 13: "mapping marker"}
STRIDE = 4  # sample every 4th frame for speed


def mark(ok, warn=False):
    return "PASS" if ok else ("WARN" if warn else "FAIL")


def check(path):
    print(f"\n=== {path}")
    meta = json.loads(subprocess.run(
        ["exiftool", "-j", "-Model", "-FirmwareVersion", "-CameraSerialNumber",
         "-ImageWidth", "-ImageHeight", "-VideoFrameRate", "-Duration#", str(path)],
        capture_output=True, text=True, check=True).stdout)[0]
    model, fw = meta.get("Model", "?"), str(meta.get("FirmwareVersion", "?"))
    w, h, fps = meta.get("ImageWidth"), meta.get("ImageHeight"), float(meta.get("VideoFrameRate", 0))
    dur = float(meta.get("Duration", 0))
    print(f"  [{mark(model == 'HERO13 Black', True)}] camera: {model}  serial {meta.get('CameraSerialNumber')}")
    print(f"  [{mark(fw.endswith('.70') or 'Labs' in fw, True)}] firmware: {fw}  (Labs 2.10.70 = H24.01.02.10.70)")
    print(f"  [{mark((w, h) == (2704, 2028))}] resolution: {w}x{h}  (need 2704x2028, 2.7K 4:3)")
    print(f"  [{mark(abs(fps - 119.88) < 1)}] frame rate: {fps:.2f} fps  (need ~119.88)")
    print(f"  [INFO] duration: {dur:.1f} s")

    try:
        ex = GoProTelemetryExtractor(str(path)); ex.open_source()
        acc, t = ex.extract_data("ACCL"); gyr, _ = ex.extract_data("GYRO"); ex.close_source()
        rate = len(t) / max(t[-1] - t[0], 1e-6)
        print(f"  [{mark(len(acc) > 0 and len(gyr) > 0 and 150 < rate < 250)}] IMU: {len(acc)} accel / {len(gyr)} gyro samples @ ~{rate:.0f} Hz")
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] IMU extraction failed: {e}")

    prm = cv2.aruco.DetectorParameters()
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), prm)
    counts, n = collections.Counter(), 0
    with av.open(str(path)) as c:
        s = c.streams.video[0]; s.thread_type = "AUTO"
        for i, fr in enumerate(c.decode(s)):
            if i % STRIDE:
                continue
            img = draw_predefined_mask(fr.to_ndarray(format="bgr24"), color=(0, 0, 0),
                                       mirror=True, gripper=False, finger=False)
            _, ids, _ = det.detectMarkers(img)
            n += 1
            if ids is not None:
                counts.update(set(int(x) for x in ids.ravel()))
    # A camera belongs to whichever gripper's finger pair it sees most; only that pair is graded
    # (the other gripper can wander into view in bimanual sessions).
    own = (0, 1) if counts[0] + counts[1] >= counts[6] + counts[7] else (6, 7)
    print(f"  tag visibility over {n} sampled frames (this camera = gripper {'G0' if own == (0, 1) else 'G1'}):")
    for tid, name in TAG_NAMES.items():
        if counts[tid] or tid in own:
            r = counts[tid] / max(n, 1)
            verdict = mark(r >= 0.8, r >= 0.6) if tid in own else "INFO"
            print(f"    [{verdict}] id {tid:2d} {name:16s} {r:6.1%}")
    other = {k: v for k, v in counts.items() if k not in TAG_NAMES}
    if other:
        print(f"    [INFO] other ids seen: {dict(other)}")
    print("  (finger tags: >=80% ideal, 60-80% OK with TH=0.6, <60% -> check lighting/finger mounts)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        check(pathlib.Path(p))
