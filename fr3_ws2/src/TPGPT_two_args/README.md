# FoundationPose & Trajectory Execution Pipeline

This repository contains the pipeline for running 6D object tracking using FoundationPose, recording robotic demonstrations with keypoints, and executing trajectory transportation for new target configurations using a Franka Emika robot arm.

## Prerequisites
- A remote GPU server running FoundationPose inside a Docker container.
- A local client (robot PC) connected to the robot arm and a RealSense camera.
- ROS installed on the client machine.

---

## Step-by-Step Execution Guide

### 1. Start FoundationPose on the Server
This step starts the inference server which will receive images from the client, perform 6D pose estimation, and send bounding box keypoints back.

**Machine:** Remote GPU Server (`10.72.18.159`)
**Directory:** `~/ssd_data/FoundationPose`

```bash
# SSH into the GPU server
ssh manthan@10.72.18.159

# Navigate to the FoundationPose directory
cd ssd_data/FoundationPose

# Run the inference script inside the docker container
docker exec -it foundationpose /opt/conda/envs/my/bin/python /workspace/server_inference.py
```
*Note: Keep this terminal open and running.*

---

### 2. Initialize the Robot Arm and Camera TF
This step launches the robot controller in gravity compensation mode and starts the camera-to-robot coordinate frame transformation (TF).

**Machine:** Local Client (Robot PC)
**Workspace:** Your ROS workspace (e.g., `~/fr3_ws`)

```bash
# Start gravity compensation controller (replace IP with your robot's actual IP if different)
roslaunch franka_example_controllers gravity_compensation.launch robot_ip:=192.168.1.12

# In a new terminal, run the eye-in-hand / camera calibration TF broadcaster
rosrun camera_calibration eye_hand_tf.py
```

---

### 3. Send Video Stream from the Client
You need to stream RealSense camera frames to the FoundationPose server. 

**Machine:** Local Client (Robot PC)
*(Note: Based on your pipeline setup, ensure you run your local client streaming script here. If running a local FoundationPose docker container to bridge the stream, you might use the command below, but typically a local ROS node like `realsense_zmq_bridge.py` is used to send frames via ZMQ to the server.)*

```bash
# Example command as provided (adjust if using a local ROS node instead of docker exec):
docker exec -it foundationpose /opt/conda/envs/my/bin/python /workspace/server_inference.py
```

---

### 4. Record a Demonstration
Record a human-guided demonstration of a skill (e.g., `pick`). This saves the object keypoints and the robot's end-effector trajectory.

**Machine:** Local Client (Robot PC)

First, start the keypoint detector for the specific skill and target object.
```bash
rosrun TPGPT_two_args keypoint_detector.py --skill pick --objects mustard0 --ee_pos
```
*Parameters:*
- `--skill`: The name of the skill being recorded (e.g., `pick`, `push`).
- `--objects`: The name of the target object being tracked (e.g., `mustard0`).
- `--ee_pos`: Flag indicating whether to record end-effector positions.

Then, start the demo recorder to save the trajectory.
```bash
rosrun TPGPT_two_args demo_recorder.py pick
```
*Parameters:*
- `pick`: The name of the skill being recorded. Ensure this matches the skill name provided to `keypoint_detector.py`.

---

### 5. Execute Skill on a New Target Configuration
Run the trajectory transportation pipeline to adapt the recorded skill to a new object location and execute it.

**Machine:** Local Client (Robot PC)

```bash
rosrun TPGPT_two_args skill_executor.py _skill_name:=pick _object_name:=mustard0 _data_dir:=/home/ravi/fr3_ws/src/TPGPT_two_args/data
```
*Parameters (passed as ROS private params):*
- `_skill_name`: The skill you want to execute (e.g., `pick`).
- `_object_name`: The target object to track during execution (e.g., `mustard0`).
- `_data_dir`: The directory containing the recorded demonstration and keypoint data.

---

## Creating and Reusing Skills

**How data is saved:**
When you record a demonstration using `demo_recorder.py` and `keypoint_detector.py`, the scripts will save the robot's end-effector trajectory and the object's 6D bounding box vertices/keypoints into the designated data directory (e.g., `/home/ravi/fr3_ws/src/TPGPT_two_args/data/<skill_name>`).

**Adding New Skills:**
1. Determine the name of your new skill (e.g., `pour`, `insert`).
2. Follow **Step 4** substituting `pick` with your new `<skill_name>` and selecting the appropriate `<object_name>`.
3. Manually guide the robot arm through the desired task motion.
4. The system will create a new subfolder or set of files under the data directory tagged with your new skill name.
5. You can then run the skill dynamically in the future by passing the new `_skill_name` to the `skill_executor.py` node as shown in **Step 5**.

**Adding New Objects:**
To manipulate new objects, ensure that the 3D object models (.obj / CAD files) are properly initialized in your FoundationPose database on the server, so that it recognizes and outputs keypoints for the requested `_object_name`.
