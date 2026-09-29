#!/usr/bin/env python3
"""Per-demo SLAM tracking QC for a processed TRumi session.

Usage: ~/trumi/.venv/bin/python analyze_session.py <session_dir> [--labels labels.csv] [--out metrics.csv]

Demos are numbered by each camera's clip order (every camera records every demo).
labels.csv (optional) has columns
demo,condition,note and is joined on demo number.

Metrics per camera clip (SLAM runs at 60 fps, so one SLAM frame = ~16.7 ms):
  tracked      share of SLAM frames with a pose
  first_track  seconds until tracking first holds for 0.5 s (30 frames)
  jumps_3cm    share of tracked frame-to-frame steps > 3 cm (pose snapping; Trossen's
               example has none - its 99th percentile step is ~9 mm)
  v95          95th-percentile hand speed, smoothed over 0.25 s windows (m/s)
  in_dataset   whether the clip contributed to an episode in dataset_plan.pkl
"""
import argparse
import pathlib
import pickle

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("session")
ap.add_argument("--labels")
ap.add_argument("--out")
args = ap.parse_args()
sess = pathlib.Path(args.session).expanduser().resolve()

clips = []
for d in sorted(sess.glob("demos/demo_*")):
    parts = d.name.split("_")
    serial, hhmmss = parts[1], parts[3]  # demo_<serial>_<date>_<time>_<file>
    h, m, s = hhmmss.split(".")[:3]
    clips.append({"dir": d, "cam": serial[-4:], "t0": int(h) * 3600 + int(m) * 60 + float(s) + float("0." + hhmmss.split(".")[3])})
# every camera records every demo, so the n-th clip of each camera is demo n
# (start times alone can't pair them: one pair on 2026-09-29 started 7 s apart)
by_cam = {}
for c in sorted(clips, key=lambda c: c["t0"]):
    by_cam.setdefault(c["cam"], []).append(c)
if len({len(v) for v in by_cam.values()}) > 1:
    print("WARNING: cameras have different clip counts:", {k: len(v) for k, v in by_cam.items()})
for cam_clips in by_cam.values():
    for i, c in enumerate(cam_clips):
        c["demo"] = i + 1
clips.sort(key=lambda c: (c["demo"], c["cam"]))

used = set()
plan = sess / "dataset_plan.pkl"
if plan.is_file():
    for ep in pickle.loads(plan.read_bytes()):
        for cam in ep.get("cameras", []):
            used.add(pathlib.Path(cam["video_path"]).parent.name)

rows = []
for c in clips:
    r = {"demo": c["demo"], "cam": c["cam"], "clip": c["dir"].name.split("_")[-1]}
    csv = c["dir"] / "camera_trajectory.csv"
    if not csv.is_file():
        r.update(tracked=0.0, slam="no trajectory (SLAM gave up or timed out)")
    else:
        df = pd.read_csv(csv)
        tr = (~df["is_lost"]).to_numpy()
        t = df["timestamp"].to_numpy()
        runs = np.convolve(tr, np.ones(30, dtype=int), "valid") == 30
        r.update(duration=round(t[-1], 1), tracked=round(tr.mean(), 3),
                 first_track=round(float(t[np.argmax(runs)]), 1) if runs.any() else None, slam="ok")
        p = df.loc[tr, ["x", "y", "z"]].to_numpy()
        if len(p) > 20:
            step = np.linalg.norm(np.diff(p, axis=0), axis=1)
            r["jumps_3cm"] = round(float((step > 0.03).mean()), 3)
            k = 15
            v = np.linalg.norm(p[k:] - p[:-k], axis=1) / (k / 60)
            r["v95"] = round(float(np.percentile(v, 95)), 2)
    r["in_dataset"] = c["dir"].name in used
    rows.append(r)

out = pd.DataFrame(rows)
if args.labels:
    out = out.merge(pd.read_csv(args.labels), on="demo", how="left")
pd.set_option("display.width", 200)
print(out.drop(columns=["clip"]).to_string(index=False))
if "condition" in out:
    g = out.groupby("condition").agg(clips=("demo", "size"), tracked=("tracked", "mean"),
                                     jumps_3cm=("jumps_3cm", "mean"), in_dataset=("in_dataset", "sum"))
    print("\nBy condition:\n" + g.round(3).to_string())
if args.out:
    out.to_csv(args.out, index=False)
    print(f"\nwrote {args.out}")
