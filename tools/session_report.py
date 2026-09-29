#!/usr/bin/env python3
"""Summarize a processed TRumi session: SLAM tracking, tag detection, calibration, output.

Usage: ~/trumi/.venv/bin/python ~/trumi_tools/session_report.py <session_dir>
"""
import collections
import json
import pathlib
import pickle
import sys

import pandas as pd

sess = pathlib.Path(sys.argv[1]).resolve()
demos = sess / "demos"
print(f"\n================ SESSION REPORT: {sess.name} ================")

mapping = next(demos.glob("mapping_*"), None)
tx = mapping / "tx_slam_tag.json" if mapping else None
print(f"[{'PASS' if mapping and (mapping / 'map_atlas.osa').is_file() else 'FAIL'}] SLAM map built")
print(f"[{'PASS' if tx and tx.is_file() else 'FAIL'}] mapping marker -> SLAM frame calibration (tx_slam_tag.json)")
if mapping:
    csv = mapping / "mapping_camera_trajectory.csv"
    if csv.is_file():
        df = pd.read_csv(csv)
        print(f"       mapping video tracked {(~df['is_lost']).mean():.0%} of frames")

cal = next(demos.glob("gripper_calibration_*"), None)
gr = cal / "gripper_range.json" if cal else None
if gr and gr.is_file():
    g = json.loads(gr.read_text())
    span = (g["max_width"] - g["min_width"]) * 1000
    print(f"[{'PASS' if span > 30 else 'WARN'}] gripper range: tag distance {g['min_width']*1000:.1f}-{g['max_width']*1000:.1f} mm "
          f"(span {span:.0f} mm; example kit: 66.9-123.6 mm)")
else:
    print("[FAIL] gripper calibration missing (gripper_range.json)")

print("\nPer-demo (lost = SLAM frames without tracking; >10 lost => demo dropped):")
print(f"  {'demo':44s} {'frames':>6s} {'lost':>5s} {'fingerL':>7s} {'fingerR':>7s}")
n_ok = n_all = 0
for d in sorted(demos.glob("demo_*")):
    n_all += 1
    csv, pkl = d / "camera_trajectory.csv", d / "tag_detection.pkl"
    frames = lost = "-"
    if csv.is_file():
        df = pd.read_csv(csv); frames = len(df); lost = int(df["is_lost"].sum())
    fl = fr = "-"
    if pkl.is_file():
        det = pickle.loads(pkl.read_bytes())
        c = collections.Counter(i for f in det for i in f["tag_dict"])
        left, right = (0, 1) if c[0] + c[1] >= c[6] + c[7] else (6, 7)
        fl, fr = f"{c[left]/max(len(det),1):.0%}", f"{c[right]/max(len(det),1):.0%}"
    ok = isinstance(lost, int) and lost <= 10
    n_ok += ok
    print(f"  {'ok ' if ok else 'BAD'} {d.name[-40:]:40s} {frames!s:>6s} {lost!s:>5s} {fl:>7s} {fr:>7s}")

plan = sess / "dataset_plan.pkl"
if plan.is_file():
    p = pickle.loads(plan.read_bytes())
    print(f"\n[{'PASS' if len(p) else 'FAIL'}] dataset plan: {len(p)} episodes from {n_all} demo videos "
          f"({n_ok} had <=10 lost SLAM frames)")
out = list((sess / "dataset_mcap").glob("*.mcap")) + list(sess.glob("*.zarr.zip"))
size = sum(f.stat().st_size for f in out) / 1e6
print(f"[{'PASS' if out else 'FAIL'}] output: {len(out)} file(s), {size:.0f} MB -> {out[0].parent if out else '-'}")
