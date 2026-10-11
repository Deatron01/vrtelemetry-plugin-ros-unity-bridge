<h1 align="center">ROS 2 / Unity Bridge</h1>

<p align="center">
  Live OpenXR HMD pose to ROS 2 and Unity, via rosbridge.<br />
  <samp>PYTHON · ROS 2 · ROSBRIDGE_SUITE · VRTELEMETRY PLUGIN</samp><br />
  <samp><a href="https://github.com/Deatron01/vrtelemetry-plugin-biosensor">BIOSENSOR PLUGIN ↗</a></samp>
</p>

### <samp>01 — WHAT IT IS</samp>

> Protocol/wire format is specified once, for every plugin, in
> [`PROTOCOL.md`](./PROTOCOL.md) -- read that first if you're modifying this
> plugin's Hub-facing code or writing a new plugin from scratch. This file
> covers what's specific to this one. (`PROTOCOL.md` here is a vendored copy
> of the canonical version in the main
> [VRTelemetry](https://github.com/Deatron01/VRTelemetry) repo's
> `plugins/PROTOCOL.md`, kept for this repo's own build-from-scratch
> instructions -- see that file's own header note.)

Out-of-process subscriber to the Core Hub's Event Router
(`/ws/hub/telemetry`). Converts the live OpenXR HMD pose to ROS's coordinate
convention and publishes `geometry_msgs/PoseStamped` for a simulated
robotic arm driven from Unity via `rosbridge_suite`.

### <samp>02 — PREREQUISITES (NOT INSTALLED BY `PluginManager`)</samp>

1. A ROS 2 distribution (Humble or newer recommended) with `rclpy` and
   `geometry_msgs` importable -- these come from the distro's own installer,
   not pip. `requirements.txt` here covers only the plugin's own WebSocket
   client.
2. `rosbridge_suite` installed and reachable:
   ```
   ros2 launch rosbridge_server rosbridge_websocket_launch.xml
   ```
   Default port 9090; Unity's ROS-TCP-Connector or any rosbridge-JSON client
   points at this, not at the Core Hub.
3. Unity project set up to consume `/vrtelemetry/hmd_pose`
   (`geometry_msgs/PoseStamped`) on the simulated arm's IK target or root
   transform.

This plugin is **disabled by default** in `plugins/registry.json` --
`PluginManager` will start the process and fail fast (visibly, in
`plugin_ros-unity-bridge.log`) at `import rclpy` if step 1 above hasn't been
done on this machine. Flip `"enabled": true` once ROS 2 and rosbridge_suite
are ready.

### <samp>03 — RUNNING STANDALONE (DEVELOPMENT, ROS 2 ENVIRONMENT ALREADY SOURCED)</samp>

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set HUB_WS_URL=ws://127.0.0.1:8000/ws/hub/telemetry
set ROS_POSE_TOPIC=/vrtelemetry/hmd_pose
.venv\Scripts\python bridge_node.py
```

Note: `rclpy`/`geometry_msgs` must be importable from whichever interpreter
runs `bridge_node.py`, which usually means this venv needs to be created
*after* sourcing the ROS 2 environment, or `--system-site-packages` passed
to `python -m venv`, depending on your ROS 2 distro's own Python packaging.

### <samp>04 — COORDINATE CONVERSION</samp>

See `coordinate_convert.py`'s docstring for the full derivation. Summary:
OpenXR (right-handed, +Y up, -Z forward) and ROS/REP-103 (right-handed,
X-forward, Y-left, Z-up) are both right-handed, so converting between them
is a fixed axis permutation with no extra sign inversion, applied to both
the position and the quaternion's vector part.

### <samp>05 — EVENT CONTRACT</samp>

Consumes `{"type": "telemetry_frame", "session_id": ..., "frame": {...}}`
from `/ws/hub/telemetry`; reads `frame["hmd_pos_x/y/z"]`,
`frame["hmd_rot_x/y/z/w"]` and `frame["hmd_tracking_valid"]`. A frame with
`hmd_tracking_valid` false is skipped, matching the Core Hub's own rule for
what counts as a real sample. Publishes nothing back onto the Event Router.

<br />

<p align="center">
  <a href="https://github.com/Deatron01"><img src="https://raw.githubusercontent.com/Deatron01/Deatron01/main/assets/icon.png" width="56" alt="Dea" /></a><br />
  <sub><i>Little chaos in a quiet mind.</i></sub><br />
  <sub><samp>MORE WORK AT <a href="https://github.com/Deatron01">GITHUB.COM/DEATRON01</a></samp></sub>
</p>
