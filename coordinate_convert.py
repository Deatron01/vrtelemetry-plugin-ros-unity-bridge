# plugins/ros-unity-bridge/coordinate_convert.py
"""OpenXR -> ROS (REP-103) coordinate conversion.

OpenXR defines its runtime space as right-handed, +Y up, -Z forward (Khronos
OpenXR 1.0 spec, section 2.4, "Coordinate System"). `src/backends/backend_openxr.py`
reads poses straight out of `xr.locate_space(...).pose` with no conversion
applied, and `TelemetryFrame` stores them exactly as received -- confirmed by
reading that file rather than assumed. So `hmd_pos_x/y/z` and
`hmd_rot_x/y/z/w` on every frame this bridge receives are in that same
OpenXR runtime convention.

ROS's REP-103 convention is also right-handed, but X-forward, Y-left, Z-up.
Both are right-handed, so this is a fixed axis permutation, not a handedness
flip -- unlike a conversion into Unity's (left-handed) convention, no extra
sign inversion beyond the permutation itself is needed here.

Mapping (OpenXR -> ROS):

    ros.x =  -openxr.z   (forward)
    ros.y =  -openxr.x   (left)
    ros.z =   openxr.y   (up)

The same permutation applies to a quaternion's vector part; the scalar part
(w) is unchanged by any pure change of axes.

Units: OpenXR positions are metres, matching ROS's convention in
`geometry_msgs/PoseStamped` -- no scaling needed.
"""

from __future__ import annotations


def openxr_pos_to_ros(pos: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = pos
    return (-z, -x, y)


def openxr_quat_to_ros(
    rot_xyzw: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x, y, z, w = rot_xyzw
    return (-z, -x, y, w)


def openxr_pose_to_ros(
    pos: tuple[float, float, float],
    rot_xyzw: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Convenience wrapper converting a full pose (position + quaternion) in one call."""
    return openxr_pos_to_ros(pos), openxr_quat_to_ros(rot_xyzw)
