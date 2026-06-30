"""Shared ROS fixtures for the Ubuntu test session.

``rospy.init_node`` may only be called once per process. Each Phase's test
file used to make its own call, which collides as soon as the suite is run
together. This fixture initializes a single node up-front so every test that
needs ROS just rides on it.
"""

from __future__ import annotations

import pytest


_ros_node_initialized = False


@pytest.fixture(scope="session", autouse=True)
def ros_node():
    """Initialize a single ROS node for the entire test session."""
    global _ros_node_initialized
    try:
        import rospy  # type: ignore

        if not rospy.core.is_initialized():
            rospy.init_node(
                "pragmabot_test_session",
                anonymous=True,
                disable_signals=True,
            )
            _ros_node_initialized = True
    except Exception:
        # ROS not installed → all Ubuntu test modules skip at module level.
        pass
    yield
