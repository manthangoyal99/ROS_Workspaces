# Ubuntu setup — ROS Noetic + Grounded SAM

This guide brings up PragmaBot reproduction on Ubuntu 20.04 with ROS Noetic
and a CUDA-capable GPU. The Mac side never needs any of this; everything
here is gated behind the runtime guards in `pragmabot.perception.grounded_sam`.

## 1. ROS Noetic + catkin workspace

Install ROS Noetic per the official Wiki (`ros-noetic-desktop-full`), then
create a catkin workspace and symlink this package:

```bash
# [UBUNTU]
mkdir -p ~/catkin_ws/src
cd ~/catkin_ws/src
ln -s ~/code/pragmabot-repro/pragmabot .
cd ~/catkin_ws
catkin build pragmabot
source devel/setup.bash
```

Verify ROS-side smoke tests:

```bash
# [UBUNTU] terminal 1
roscore

# [UBUNTU] terminal 2
pytest tests/ubuntu/ -v
python scripts/smoke_phase2_ubuntu.py
```

## 2. Installing Grounded SAM

```bash
# [UBUNTU]
# Heavy deps — needs CUDA toolkit + matching torch wheel.
pip install groundingdino-py segment-anything

# Download checkpoints
mkdir -p ~/pragmabot_models
cd ~/pragmabot_models

# SAM vit_b (smallest, fastest — recommended for real-time)
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth

# GroundingDINO
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth
```

GroundingDINO's config file ships inside the installed package:

```bash
python -c "import groundingdino, os; \
  print(os.path.join(os.path.dirname(groundingdino.__file__), 'config', 'GroundingDINO_SwinT_OGC.py'))"
```

## 3. Configure PragmaBot

Edit `pragmabot/config/config.yaml`:

```yaml
perception:
  backend: grounded_sam
  grounding_dino_config: /path/to/GroundingDINO_SwinT_OGC.py
  grounding_dino_checkpoint: /home/<user>/pragmabot_models/groundingdino_swint_ogc.pth
  sam_checkpoint: /home/<user>/pragmabot_models/sam_vit_b_01ec64.pth
  sam_model_type: vit_b
  device: cuda
```

## 4. Smoke tests

```bash
# [UBUNTU]
pytest tests/ubuntu/test_phase3_ubuntu.py -v
python scripts/smoke_phase3_ubuntu.py
```

The Ubuntu smoke script prints `mode: real` if checkpoints are loaded
successfully or `mode: stub` otherwise. Both are acceptable for a passing
smoke run; only `mode: real` exercises Grounded SAM end-to-end.

## 5. Franka + MoveIt setup

### Prerequisites

```bash
# [UBUNTU]
sudo apt install ros-noetic-moveit ros-noetic-panda-moveit-config
# franka_ros (see https://frankaemika.github.io/docs/installation_linux.html):
sudo apt install ros-noetic-franka-gazebo ros-noetic-franka-control ros-noetic-franka-gripper
```

### Launch order (Gazebo simulation)

```bash
# [UBUNTU] terminal 1
roslaunch franka_gazebo panda.launch x:=0 y:=0 z:=0 \
  world:=$(rospack find franka_gazebo)/world/stone.sdf \
  controller:=position_joint_trajectory_controller rviz:=true

# [UBUNTU] terminal 2
roslaunch panda_moveit_config panda_moveit.launch

# [UBUNTU] terminal 3
roslaunch pragmabot launch_pragmabot.launch use_real_robot:=false
```

Or use the convenience launch:

```bash
roslaunch pragmabot launch_pragmabot_sim.launch
```

### Launch order (real robot)

```bash
# [UBUNTU] follow the franka_ros real-robot setup first, then:
roslaunch pragmabot launch_pragmabot.launch use_real_robot:=true robot_ip:=<FCI_IP>
```

### Workspace safety

`FrankaRobot._check_workspace_limits` rejects any target position that falls
outside `robot.workspace_limits` (set in `config.yaml`). The defaults are a
conservative box in front of the arm:

```yaml
robot:
  workspace_limits:
    x: [0.20, 0.70]
    y: [-0.40, 0.40]
    z: [0.00, 0.60]
```

Every motion-emitting method (`move_to_pose`, `move_cartesian_path`,
`execute_pick/place/push`) calls this check; failure is logged and returned
as `False` rather than raised so the pipeline keeps going.

### Smoke tests

```bash
# [UBUNTU]
pytest tests/ubuntu/test_phase4_ubuntu.py -v
python scripts/smoke_phase4_ubuntu.py
```

## 6. Returning to Mac

You can keep the Mac config (`perception.backend: stub`) in a separate branch
or local override; `git status` should show the Mac default checked in. The
Ubuntu-only paths above never load on Mac — `grounded_sam.py` carries an
`ImportError` guard at the top.
