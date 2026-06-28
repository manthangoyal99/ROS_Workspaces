import rospy
from sensor_msgs.msg import Image
import numpy as np
import cv2
import requests
import base64
from franky import Robot, CartesianMotion, Affine, ReferenceType, JointMotion

# ---------------- WORKSPACE LIMITS ----------------
X_MIN, X_MAX = -0.15, 0.15
Y_MIN, Y_MAX = -0.25, 0.25
Z_MIN, Z_MAX = -0.10, 0.10

STEP_X = 0.015
STEP_Y = 0.01
STEP_Z = 0.03

YOLO_URL = "http://10.72.18.159:5000"

# ---------------- ROBOT INIT ----------------
robot = Robot("192.168.1.14")
robot.relative_dynamics_factor = 0.04

q = robot.current_joint_positions
q_target = q.copy()
q_target[5] += 1.57
robot.move(JointMotion(q_target))

cur_x = cur_y = cur_z = 0.0
y_dir = 1

latest_frame = None
frame_id = 0

# ---------------- ROS IMAGE CALLBACK ----------------
def image_cb(msg):
    global latest_frame, frame_id

    img = np.frombuffer(msg.data, dtype=np.uint8)
    img = img.reshape(msg.height, msg.width, 3)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    latest_frame = img
    frame_id += 1

# ---------------- SAFE MOVE ----------------
def safe_move(dx, dy, dz):
    global cur_x, cur_y, cur_z

    nx = cur_x + dx
    ny = cur_y + dy
    nz = cur_z + dz

    if not (X_MIN <= nx <= X_MAX):
        return False
    if not (Y_MIN <= ny <= Y_MAX):
        return False
    if not (Z_MIN <= nz <= Z_MAX):
        return False

    motion = CartesianMotion(Affine([dx, dy, dz]), ReferenceType.Relative)
    robot.move(motion)

    cur_x, cur_y, cur_z = nx, ny, nz
    return True

# ---------------- HTTP HELPERS ----------------
def send_image(endpoint, frame, timeout=1.0):
    _, buf = cv2.imencode(".jpg", frame)

    files = {
        "image": ("frame.jpg", buf.tobytes(), "image/jpeg")
    }

    r = requests.post(endpoint, files=files, timeout=timeout)
    return r
def detect_face(show):
    if latest_frame is None:
        return False

    frame = latest_frame.copy()

    # ---- FAST DETECT ----
    try:
        import time
        time.sleep(5)
        r = send_image(f"{YOLO_URL}/detect", frame, timeout=(2, 2))
        if r.status_code != 200:
            return False

        detected = r.json().get("face_detected", False)

    except Exception:
        return False

    if not detected:
        if show:
            cv2.imshow("Franka Camera", frame)
            cv2.waitKey(1)
        return False

    # =================================================
    # FACE FOUND → SAVE RAW FRAME
    # =================================================
    cv2.imwrite("capture_raw.jpg", frame)
    print("Raw capture saved")

    print("Face detected — stopping robot and transforming")

    # ---- SLOW TRANSFORM ----
    try:

        r = send_image(f"{YOLO_URL}/transform", frame, timeout=(2, 120))
        if r.status_code == 200:
            data = r.json()

            prompt_used = data.get("prompt")
            img_base64 = data.get("image")

            img_bytes = base64.b64decode(img_base64)

            stylized = cv2.imdecode(
                np.frombuffer(img_bytes, np.uint8),
                cv2.IMREAD_COLOR
            )

            print("Prompt used:", prompt_used)

            cv2.imwrite(f"capture_{prompt_used}.jpg", stylized)
            print("Stylized image saved")

            if show:
                cv2.imshow("Stylized", stylized)

    except Exception:
        pass

    if show:
        cv2.imshow("Franka Camera", frame)
        cv2.waitKey(1)

    return True
    
# ---------------- SEARCH MOTION ----------------
def search(show):
    global y_dir, frame_id

    print("Starting bounded face search")
    last_seen = -1

    while not rospy.is_shutdown():
        if frame_id == last_seen:
            continue
        last_seen = frame_id

        if detect_face(show):
            print("Face found — stopping search")
            return

        dy = STEP_Y * y_dir
        if safe_move(0, dy, 0):
            continue

        y_dir *= -1
        if safe_move(STEP_X, 0, 0):
            continue

        if safe_move(0, 0, STEP_Z):
            continue

        print("Search space fully explored")
        return

# ---------------- MAIN ----------------
def main(show):
    rospy.init_node("franka_face_search")

    rospy.Subscriber("/camera/color/image_raw", Image, image_cb, queue_size=1)

    print("Waiting for camera...")
    while latest_frame is None and not rospy.is_shutdown():
        rospy.sleep(0.1)
    print("Performing random motion sequence before search")

    #########################
    import random
    from scipy.spatial.transform import http://10.72.18.159:5000Rotation as R

    motions = []

    for _ in range(5):  # number of random moves
        dx = random.uniform(-0.03, 0.03)
        dy = random.uniform(-0.03, 0.03)
        dz = random.uniform(-0.02, 0.02)

        rx = random.uniform(-0.1, 0.1)   # roll
        ry = random.uniform(-0.1, 0.1)   # pitch
        rz = random.uniform(-0.2, 0.2)   # yaw

        if safe_move(dx, dy, dz):

            rot = R.from_euler('xyz', [rx, ry, rz])
            quat = rot.as_quat()  # [x, y, z, w]

            motion = CartesianMotion(
                Affine(
                    np.array([0.0, 0.0, 0.0]),
                    np.array(quat)
                ),
                ReferenceType.Relative
            )

            robot.move(motion)

            motions.append((dx, dy, dz, rx, ry, rz))
            rospy.sleep(0.5)

    print("Returning to original pose")

    # Reverse in opposite order
    for dx, dy, dz, rx, ry, rz in reversed(motions):

        # Reverse rotation first
        rot = R.from_euler('xyz', [-rx, -ry, -rz])
        quat = rot.as_quat()

        motion = CartesianMotion(
            Affine(
                np.array([0.0, 0.0, 0.0]),
                np.array(quat)
            ),
            ReferenceType.Relative
        )

        robot.move(motion)
        rospy.sleep(0.3)

        # Then reverse translation
        safe_move(-dx, -dy, -dz)
        rospy.sleep(0.3)

    print("Random motion complete")
    # ---------------------------------------------------------

    search(show)

    if show:
        cv2.destroyAllWindows()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    main(args.show)