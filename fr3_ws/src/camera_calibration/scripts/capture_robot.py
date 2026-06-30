#!/usr/bin/env python3
import rospy
import csv
import sys
import select
import os
from franka_msgs.msg import FrankaState


class PoseRecorder:
    def __init__(self, mode):
        rospy.init_node('3d_pose_recorder', anonymous=True)

        assert mode in ["training", "validation"], \
            "Mode must be 'training' or 'validation'"

        self.mode = mode
        self.latest_msg = None

        SAVE_DIR = "/home/ravi/fr3_ws/src/camera_calibration/data"
        os.makedirs(SAVE_DIR, exist_ok=True)

        if mode == "training":
            self.filepath = os.path.join(SAVE_DIR, "robo_3d_pose.csv")
        else:
            self.filepath = os.path.join(
                SAVE_DIR, "robo_3d_pose_validation.csv"
            )

        self.sub = rospy.Subscriber(
            "/franka_state_controller/franka_states",
            FrankaState,
            self.callback
        )

        print("Waiting for robot connection...")
        rospy.wait_for_message(
            "/franka_state_controller/franka_states",
            FrankaState
        )
        print("Robot connected!")

    def callback(self, msg):
        self.latest_msg = msg

    def save_snapshot(self, point_id):
        if self.latest_msg is None:
            print("No data received yet!")
            return

        O_T_EE = self.latest_msg.O_T_EE
        x, y, z = O_T_EE[12], O_T_EE[13], O_T_EE[14]

        row = [point_id, x, y, z]

        with open(self.filepath, 'a', newline='') as f:
            csv.writer(f).writerow(row)

        print(
            f"[{self.mode.upper()}] "
            f"Saved point '{point_id}': "
            f"x={x:.4f}, y={y:.4f}, z={z:.4f}"
        )

    def run(self):
        # Write header once
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w', newline='') as f:
                csv.writer(f).writerow(["id", "x", "y", "z"])

        print("\n" + "=" * 50)
        print(f"Mode        : {self.mode.upper()}")
        print(f"Recording to: {self.filepath}")
        print("INSTRUCTIONS:")
        print("  <id> + ENTER : record current TCP position")
        print("  Ctrl+C       : exit")
        print("=" * 50 + "\n")

        try:
            while not rospy.is_shutdown():
                if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                    point_id = sys.stdin.readline().strip()
                    if point_id == "":
                        print("Please enter a point id.")
                        continue

                    self.save_snapshot(point_id)
                    print("Ready for next point...")

        except KeyboardInterrupt:
            pass

        print("\nRecording finished.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: capture_robot.py [training|validation]")
        sys.exit(1)

    mode = sys.argv[1].lower()
    recorder = PoseRecorder(mode)
    recorder.run()
