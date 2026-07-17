# Capture pipeline glue (GPLv2).
# Screen/window capture (mss), then hands frames to bitgil_core's change
# detector and ROI cropping. Kept thin; heavy logic lives in bitgil_core.
# TODO(M1): implement mss-based capture of the full screen or a chosen window.
