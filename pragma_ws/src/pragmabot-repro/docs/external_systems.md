# External Systems: FoundationPose + TPGPT_two_args

Two external services that pragmabot-repro will integrate with for the
"open skill" workflow (novel-skill demonstration + execution). Both have
their own private repos; this file captures their current operating
procedure and how they fit alongside pragmabot.

## High-level flow

```
                              [robot Ubuntu PC]                                  [GPU server (10.72.18.159)]
RGB+depth ─► RealSense ZMQ bridge ─────────► (network) ─────────────► FoundationPose docker (server_inference.py)
                                                                              │
                                                                              ▼
                                                              6D pose / labeled bbox per object (sent back)
                                                                              │
                                                                              ▼
                              keypoint_detector.py  ──►  demo_recorder.py  ──►  skill_executor.py
                                  (TPGPT_two_args)        (TPGPT_two_args)        (TPGPT_two_args)
                                                                              │
                                                                              ▼
                                                                  cartesian impedance controller
                                                                              │
                                                                              ▼
                                                                          Franka FR3
```

- Demos are recorded under gravity-compensation control (human guides the arm).
- Execution runs under cartesian impedance control.
- FoundationPose requires per-object meshes (`.obj`) registered on the
  server before that object name can be tracked.
- TPGPT_two_args converts pose bboxes into keypoints, ingests the human
  demo, then "transports" the trajectory to new (pick_bb, place_bb)
  configurations at execution time.

## Repos

| Repo | Lives on | Notes |
|---|---|---|
| `pragmabot-repro` | Mac (canonical) + robot Ubuntu | This repo. |
| `tpgpt-two-args`  | robot Ubuntu (`~/fr3_ws/src/TPGPT_two_args`) | Keypoint detector + demo recorder + skill executor. |
| `foundation-pose-pragmabot` | GPU server `manthan@10.72.18.159:~/ssd_data/FoundationPose` | Private mirror of NVlabs/FoundationPose with our additions; `upstream` remote tracks NVlabs. |

## Operating procedure (manual — to be automated by pragmabot launcher)

### 1. Start FoundationPose on the GPU server

```bash
ssh manthan@10.72.18.159
cd ssd_data/FoundationPose
docker exec -it foundationpose /opt/conda/envs/my/bin/python /workspace/server_inference.py
```
Leave the terminal open.

### 2. Robot arm + eye-hand TF (robot Ubuntu)

```bash
# Demo mode — gravity compensation so the human can backdrive the arm.
roslaunch franka_example_controllers gravity_compensation.launch robot_ip:=192.168.1.12

# Camera → robot TF broadcaster.
rosrun camera_calibration eye_hand_tf.py
```

### 3. Stream RGB-D frames to the GPU server

```bash
# Local ZMQ bridge from RealSense → GPU server.
# (Exact node TBD; the upstream README has a placeholder docker exec command,
#  but in practice a local ROS node like realsense_zmq_bridge.py is used.)
```

### 4. Record a demo

Per skill + object combination:

```bash
# Start the keypoint detector for the skill + the target object(s).
rosrun TPGPT_two_args keypoint_detector.py \
    --skill pick \
    --objects mustard0 \
    --ee_pos

# In a second terminal, start the recorder.
rosrun TPGPT_two_args demo_recorder.py pick
```

Then the human leads the arm through the motion. Data is written to
`~/fr3_ws/src/TPGPT_two_args/data/<skill_name>/`.

### 5. Execute a known skill on a new target configuration

```bash
# Switch the robot to cartesian impedance control (not gravity-comp).
# Then:
rosrun TPGPT_two_args skill_executor.py \
    _skill_name:=pick \
    _object_name:=mustard0 \
    _data_dir:=/home/ravi/fr3_ws/src/TPGPT_two_args/data
```

Verified: skill_executor generalises the recorded demo to new object
locations, *provided* both the recorded keypoints and the demo had the
object at the same place when recorded.

## Adding new objects

The new object's CAD mesh (`.obj`) must be registered with FoundationPose
before its name can be queried. Done on the GPU server side.

## Adding new skills

1. Pick a name (`pour`, `insert`, etc.) and a target object.
2. Run **step 4** with that skill name.
3. Human leads the arm through the motion.
4. Data lands in `data/<new_skill_name>/`.
5. From then on, skill_executor (step 5) can run it on new
   `(object, target)` placements.

## Open integration questions tracked here

- **Where does pragmabot's task planner call into this?** Likely via a
  thin HTTP/gRPC client per service rather than ROS service calls, to
  keep the pragmabot node independent of the TPGPT package.
- **How are success / failure criteria for novel skills generated?**
  Currently nowhere. Proposed: when the VLM proposes a novel skill, it
  also emits `success_criteria` + `failure_criteria` as natural-language
  prompts that the existing success_detector VLM evaluates against
  before/after frames. Treat the same way as built-in skills.
- **MoveIt vs cartesian impedance:** the existing pragmabot FrankaRobot
  uses MoveIt for everything. TPGPT_two_args wants cartesian impedance.
  Decision: introduce a `robot.controller` config (`moveit` |
  `cartesian_impedance`) and let the planner pick per-skill.
- **Demo capture in pragmabot's UI:** Gradio panel with start/stop demo
  recording, skill name field, object name dropdown (populated from
  registered FoundationPose meshes).
