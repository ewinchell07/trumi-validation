# TRumi validation — 2026-09-29

First hands-on validation of the [Trossen TRumi](https://docs.trossenrobotics.com/trumi/) handheld
gripper (a UMI-style GoPro + ArUco-finger data collector) on the Titus RTX 5090 laptop, ending in
a two-gripper conveyor-belt capture at four belt speeds.

**Start with the experiment record:** [`experiment/index.html`](experiment/index.html) (also published as a private Claude artifact: https://claude.ai/artifact/JroLA5GUTmSGd88ySTMEw7)
(results, what broke, what to change).

| | |
|---|---|
| Test plan (pre-registered checklist) | [`test-plan/index.html`](test-plan/index.html) (artifact: https://claude.ai/artifact/QoasZrsg1ycqfGULmt8yUe) |
| Experiment record | [`experiment/index.html`](experiment/index.html) |
| Processed data (MCAP episodes, plans, calibration) | Hugging Face `ewinchell07/trumi-validation-2026-09-29` (private dataset) |
| Raw GoPro clips | on the laptop at `~/trumi_sessions/` (not uploaded) |

## Layout

```
tools/        check_clip.py        per-clip QC: camera/firmware/2.7K/120fps, IMU, finger-tag visibility
              process_session.sh   full pipeline wrapper (steps 00-07) + report; TRIM=1 for off-map starts
              session_report.py    pass/fail summary for a processed session
              settings_qr.png      GoPro Labs QR for the Labs-Trumi preset (2.7K 4:3 120fps)
analysis/     analyze_session.py   per-demo SLAM tracking metrics (tracked %, pose-jump rate, speed)
patches/      trumi-local.patch    changes to upstream TRumi (commit in UPSTREAM_COMMIT)
sessions/     per-session labels.csv, demo_metrics.csv, session reports, clip timelines
test-plan/    the checklist page used on the day
experiment/   the experiment record page
```

## Reproducing

```bash
git clone https://github.com/TrossenRobotics/trumi ~/trumi && cd ~/trumi
git checkout $(cat /path/to/trumi-validation/patches/UPSTREAM_COMMIT)
git apply /path/to/trumi-validation/patches/trumi-local.patch
uv sync                                   # pipeline Python env
# build the ORB-SLAM3 docker image per the TRumi docs (image name: orb_slam3)

~/trumi-validation/tools/process_session.sh <session_dir>          # tabletop session
TRIM=1 ~/trumi-validation/tools/process_session.sh <session_dir>   # demos that start off-map
~/trumi/.venv/bin/python analysis/analyze_session.py <session_dir> --labels sessions/<s>/labels.csv
```

`<session_dir>/raw_videos/` takes a flat dump of both cameras' clips. Prefix each file with its
camera (e.g. `3778_GX010004.MP4`): both GoPros number files the same way. The largest clip is the
mapping video, and each camera's earliest remaining clip is its gripper calibration.

## Local changes to TRumi (`patches/trumi-local.patch`)

- `cv_util.py`: ArUco ids are `(N,)` in OpenCV 5, `(N,1)` in OpenCV 4 — ravel before indexing.
- `pyproject.toml`: pin `multimethod<2` (scikit-fda breaks on 2.x).
- `06_generate_dataset_plan.py`: new `--trim_untracked_ends` / `--min_tracked_run`. Each clip is trimmed
  to its SLAM-tracked span before cameras are matched into episodes, so demos that start outside the
  mapped area are kept instead of dropped. Off by default (upstream behaviour unchanged).
