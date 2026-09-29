#!/usr/bin/env python3
"""Test 1: does SLAM track demo clips if they start with the map already in view?

Hypothesis: clips that begin off-map fail because this ORB-SLAM3 build breaks when it
relocalizes mid-clip (huge IMU velocity, then flicker or hang), not because of the scene.
Clips that localize on frame 0 tracked 100% in the same scene.

For each clip: find the raw frame where SLAM first recognized the map in a previous run,
write a trimmed copy starting there (video re-encoded from that frame; imu_data.json frame
and IMU timestamps shifted so it becomes t=0), then run SLAM on the copies.

Usage: trim_start_test.py <session_dir> <out_dir> [clip-substring ...]
       (then: 03_batch_slam.py --input_dir <out_dir> --map_path ... --max_lost_frames 0)
"""
import json
import pathlib
import re
import subprocess
import sys

import pandas as pd

sess, out = pathlib.Path(sys.argv[1]).expanduser(), pathlib.Path(sys.argv[2]).expanduser()
only = sys.argv[3:]
STRIDE = 2  # SLAM frame = every 2nd raw frame at 120 fps


def first_map_frame(d):
    """Raw frame index where SLAM first had a pose, from a previous run's outputs."""
    csv = d / "camera_trajectory.csv"
    if csv.is_file():
        df = pd.read_csv(csv)
        tracked = df.index[~df["is_lost"]]
        return int(df.loc[tracked[0], "frame_idx"]) if len(tracked) else None
    txt = (d / "slam_stdout.txt").read_text(errors="ignore") if (d / "slam_stdout.txt").is_file() else ""
    m = re.search(r"n_lost_frames=(\d+)\n(?:.*\n){0,3}?Relocalized!!", txt)
    if m:  # every SLAM frame before the first relocalization was lost
        return int(m.group(1)) * STRIDE
    return None


out.mkdir(parents=True, exist_ok=True)
for d in sorted(sess.glob("demos/demo_*")):
    if only and not any(s in d.name for s in only):
        continue
    k = first_map_frame(d)
    if k is None:
        print(f"skip {d.name}: never recognized the map")
        continue
    t = out / d.name
    t.mkdir(exist_ok=True)
    imu = json.loads((d / "imu_data.json").read_text())
    ts = imu["img_timestamps_s"]
    t0 = ts[k]
    imu["img_timestamps_s"] = [x - t0 for x in ts[k:]]
    for key in ("ACCL", "GYRO"):
        keep = [(x - t0, v) for x, v in zip(imu[key]["timestamps_s"], imu[key]["data"]) if x >= t0 - 0.05]
        imu[key]["timestamps_s"] = [x for x, _ in keep]
        imu[key]["data"] = [v for _, v in keep]
    (t / "imu_data.json").write_text(json.dumps(imu))
    if not (t / "raw_video.mp4").is_file():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(d / "raw_video.mp4"), "-vf", f"trim=start_frame={k},setpts=PTS-STARTPTS",
             "-r", "120000/1001", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "12", "-pix_fmt", "yuv420p", str(t / "raw_video.mp4")],
            check=True)
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(t / "raw_video.mp4")],
                           capture_output=True, text=True).stdout.strip())
    ok = "OK" if n == len(imu["img_timestamps_s"]) else f"MISMATCH ({len(imu['img_timestamps_s'])} timestamps)"
    print(f"{d.name}: start at raw frame {k} ({t0:.2f}s), {n} frames {ok}")
