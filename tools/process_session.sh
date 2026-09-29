#!/usr/bin/env bash
# Run the full TRumi pipeline on one session with the thresholds validated on
# the example dataset, then print a pass/fail summary.
#
# Usage: ~/trumi_tools/process_session.sh <session_dir>
#   <session_dir>/raw_videos/*.MP4  (flat dump is fine: largest clip -> mapping,
#                                    earliest remaining clip -> gripper calibration)
# Env:   TH=0.6 (finger-tag detection threshold for steps 05/06)
#        FORMAT=mcap|zarr (default mcap)
#        TRIM=1 keep demos that start/end outside the mapped area: SLAM runs with no
#               lost-frame limit, step 06 trims each clip to its tracked span
#        TIMEOUT_MULT=16 per-clip SLAM timeout as a multiple of clip length (TRIM=1 sets 60)
#        MAX_LOST=60 SLAM gives up after this many lost frames (0 = never; TRIM=1 sets 0)
set -euo pipefail
[ $# -eq 1 ] || { sed -n 2,10p "$0"; exit 1; }
SESSION=$(realpath "$1"); TH=${TH:-0.6}; FORMAT=${FORMAT:-mcap}; TRIM=${TRIM:-0}
[ "$TRIM" = 1 ] && MAX_LOST=${MAX_LOST:-0} || MAX_LOST=${MAX_LOST:-60}
# SLAM without a lost-frame limit keeps trying to relocalize, which is slow; give it longer
[ "$TRIM" = 1 ] && TIMEOUT_MULT=${TIMEOUT_MULT:-60} || TIMEOUT_MULT=${TIMEOUT_MULT:-16}
# SLAM runs in Docker; if this login predates the docker group membership, re-exec under it.
if ! docker info >/dev/null 2>&1; then
  if [ -z "${_TRUMI_SG:-}" ] && sg docker -c true 2>/dev/null; then
    exec sg docker -c "_TRUMI_SG=1 TH=$TH FORMAT=$FORMAT TRIM=$TRIM MAX_LOST=$MAX_LOST TIMEOUT_MULT=$TIMEOUT_MULT $(printf %q "$0") $(printf %q "$SESSION")"
  fi
  echo "Cannot reach Docker (needed for SLAM). Try: newgrp docker, or reboot."; exit 1
fi
cd ~/trumi
PY=.venv/bin/python; S=scripts/scripts_slam_pipeline; CAL=example/calibration
step() { echo; echo "############### $1 ###############"; }
t0=$SECONDS

# 00 moves clips out of raw_videos/, so on a re-run it has nothing left to do
step "00 organize videos";  [ -d "$SESSION/demos" ] && echo "already organized" || $PY $S/00_process_videos.py "$SESSION"
step "01 extract IMU";      $PY $S/01_extract_gopro_imu.py "$SESSION"
MAP_DIR=$(ls -d "$SESSION"/demos/mapping_* | head -1)
step "02 build SLAM map"
[ -f "$MAP_DIR/map_atlas.osa" ] || $PY $S/02_create_map.py --input_dir "$MAP_DIR" --map_path "$MAP_DIR/map_atlas.osa"
[ -f "$MAP_DIR/map_atlas.osa" ] || { echo "MAP FAILED - see $MAP_DIR/slam_stdout_mapping.txt"; exit 1; }
SFS=$(grep -o 'skip=[0-9]*' "$MAP_DIR/slam_stdout_mapping.txt" | head -1 | cut -d= -f2); SFS=${SFS:-2}
echo "SLAM frame stride: $SFS"
step "03 localize demos";   $PY $S/03_batch_slam.py --input_dir "$SESSION/demos" --map_path "$MAP_DIR/map_atlas.osa" --max_lost_frames "$MAX_LOST" --timeout_multiple "$TIMEOUT_MULT"
step "04 detect ArUco";     $PY $S/04_detect_aruco.py --input_dir "$SESSION/demos" \
    --camera_intrinsics $CAL/gopro13_intrinsics_2_7k.json --aruco_yaml $CAL/aruco_config.yaml --slam_frame_stride "$SFS"
step "05 calibrate";        $PY $S/05_run_calibrations.py --input_dir "$SESSION" --tag_det_threshold "$TH"
step "06 dataset plan";     $PY $S/06_generate_dataset_plan.py --input_dir "$SESSION" --slam_frame_stride "$SFS" --finger_tag_det_th "$TH" \
    $([ "$TRIM" = 1 ] && echo --trim_untracked_ends)
step "07 write $FORMAT"
if [ "$FORMAT" = zarr ]; then
  $PY $S/07_generate_zarr_dataset.py --output "$SESSION/dataset.zarr.zip" --slam_frame_stride "$SFS" "$SESSION"
else
  $PY $S/07_generate_mcap_dataset.py --output "$SESSION/dataset_mcap" --slam_frame_stride "$SFS" "$SESSION"
fi
echo; echo "Pipeline finished in $(( (SECONDS - t0) / 60 ))m$(( (SECONDS - t0) % 60 ))s"
$PY ~/trumi_tools/session_report.py "$SESSION"
