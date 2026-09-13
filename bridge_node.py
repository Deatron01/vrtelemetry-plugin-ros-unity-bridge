# plugins/ros-unity-bridge/bridge_node.py
"""ROS 2 bridge: Core Hub telemetry -> geometry_msgs/PoseStamped -> Unity.

Subscribes to the Core Hub's Event Router (`/ws/hub/telemetry` -- see the
naming note at the top of `src/interfaces/api/event_router.py`), converts
the HMD's live OpenXR pose to ROS's convention (`coordinate_convert.py`),
and publishes `geometry_msgs/PoseStamped` on a standard ROS 2 topic. From
there, `rosbridge_suite` (`ros2 launch rosbridge_server
rosbridge_websocket_launch.xml`) exposes that topic over its own WebSocket
port (default 9090) for the Unity side -- ROS-TCP-Connector or a
rosbridge-JSON client subscribes to it exactly like any other ROS 2 topic.
This node does not talk to Unity or rosbridge_suite directly; it talks to
ROS 2's normal pub/sub, and rosbridge_suite is what makes that reachable
from Unity.

This node is a subscriber to the Core Hub, never a dependency of it: if ROS 2
is not installed, rosbridge_suite is not running, or this process crashes,
telemetry recording is completely unaffected -- see
`src/storage/tee_sink.py`'s docstring in the Core Hub for the mechanism that
guarantees this.

## Requires a ROS 2 distribution on this machine

`rclpy` and `geometry_msgs` ship with a ROS 2 distribution's own installer
(apt on Ubuntu, or a Windows ROS 2 build), not via pip -- `requirements.txt`
here covers only the WebSocket client (`websockets`), which *is* pip-
installable and is what `PluginManager`'s isolated venv actually provides.
Source the ROS 2 environment (`source /opt/ros/<distro>/setup.bash`, or the
Windows equivalent) before this plugin is launched, or `PluginManager` will
start the process and it will fail at the `import rclpy` line -- which shows
up as a normal "plugin crashed, will retry" cycle in
`plugin_ros-unity-bridge.log`, not a hang.

## Running

    ros2 launch rosbridge_server rosbridge_websocket_launch.xml   # once, separately
    set HUB_WS_URL=ws://127.0.0.1:8000/ws/hub/telemetry
    python bridge_node.py

    # Inspect the published topic from another terminal:
    ros2 topic echo /vrtelemetry/hmd_pose
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

import rclpy
import websockets
from coordinate_convert import openxr_pose_to_ros
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s ros-unity-bridge %(levelname)s %(message)s"
)
logger = logging.getLogger("ros_unity_bridge")


class HubToRosBridge(Node):
    """Owns the ROS 2 publisher. `publish_hmd_pose` is called from the
    WebSocket thread below, not from ROS 2's own executor -- `create_publisher`
    and `.publish()` are documented thread-safe in rclpy, so no additional
    locking is needed here."""

    def __init__(self, frame_id: str, topic: str) -> None:
        super().__init__("vrtelemetry_hub_bridge")
        self._publisher = self.create_publisher(PoseStamped, topic, 10)
        self._frame_id = frame_id
        self.get_logger().info(f"Publishing HMD pose on '{topic}' (frame_id='{frame_id}').")

    def publish_hmd_pose(self, frame: dict[str, Any]) -> None:
        # Same validity rule the Core Hub applies before it records a frame
        # at all (see TelemetryEngine._run_pcvr_mode's has_valid_source
        # check) -- a stub/zeroed pose from a session that isn't tracking
        # yet must not drive the simulated arm.
        if not frame.get("hmd_tracking_valid", 0):
            return

        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._frame_id

        position, orientation = openxr_pose_to_ros(
            pos=(frame["hmd_pos_x"], frame["hmd_pos_y"], frame["hmd_pos_z"]),
            rot_xyzw=(
                frame["hmd_rot_x"],
                frame["hmd_rot_y"],
                frame["hmd_rot_z"],
                frame["hmd_rot_w"],
            ),
        )
        msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = position
        (
            msg.pose.orientation.x,
            msg.pose.orientation.y,
            msg.pose.orientation.z,
            msg.pose.orientation.w,
        ) = orientation

        self._publisher.publish(msg)


class HubSubscriber:
    """The WebSocket half, on its own asyncio loop and thread -- ROS 2's own
    executor (`rclpy.spin`) owns the main thread, and the two must not block
    each other."""

    def __init__(self, hub_ws_url: str, token: str | None, on_frame) -> None:
        self._hub_ws_url = hub_ws_url
        self._token = token
        self._on_frame = on_frame

    def _connect_url(self) -> str:
        url = self._hub_ws_url
        params = []
        if self._token:
            params.append(f"token={self._token}")
        params.append("plugin_id=ros-unity-bridge")
        sep = "&" if "?" in url else "?"
        return url + sep + "&".join(params)

    async def run(self) -> None:
        url = self._connect_url()
        backoff = 1.0
        while True:
            try:
                logger.info(f"Connecting to Core Hub at {self._hub_ws_url}...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected. Streaming HMD pose to ROS 2.")
                    backoff = 1.0
                    async for raw in ws:
                        message = json.loads(raw)
                        if message.get("type") == "telemetry_frame":
                            self._on_frame(message["frame"])
            except (websockets.WebSocketException, OSError) as exc:
                logger.warning(f"Hub connection lost ({exc}); reconnecting in {backoff:.0f}s.")
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)


def main() -> None:
    hub_ws_url = os.environ.get("HUB_WS_URL", "ws://127.0.0.1:8000/ws/hub/telemetry")
    token = os.environ.get("HUB_PLUGIN_TOKEN")
    topic = os.environ.get("ROS_POSE_TOPIC", "/vrtelemetry/hmd_pose")
    frame_id = os.environ.get("ROS_FRAME_ID", "vr_play_area")

    rclpy.init()
    node = HubToRosBridge(frame_id=frame_id, topic=topic)

    subscriber = HubSubscriber(hub_ws_url, token, on_frame=node.publish_hmd_pose)
    ws_loop = asyncio.new_event_loop()
    ws_thread = threading.Thread(
        target=lambda: ws_loop.run_until_complete(subscriber.run()),
        daemon=True,
        name="hub-subscriber",
    )
    ws_thread.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
