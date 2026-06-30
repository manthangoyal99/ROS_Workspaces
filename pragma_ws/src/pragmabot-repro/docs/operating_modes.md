# Pragmabot — operating modes & dev workflow

This is the day-to-day handbook for the project as of June 2026. It
covers:

- The **two operating modes** the system can run in (legacy MoveIt vs new
  FoundationPose+TPGPT) — what's wired up today, what's still in
  integration, and the commands for each.
- The **three machines** involved (Mac, robot Ubuntu, GPU server) and
  which repo is canonical on which.
- The **commit/pull workflow** — Mac is the canonical commit point;
  robot Ubuntu and the GPU server pull from GitHub.

It deliberately repeats commands and context so a new contributor (or
future-you in two weeks) can find everything in one place.

---

## 1. Two operating modes

### Mode A — Legacy (MoveIt + hand-coded skills)

What's running today. Pragmabot's task planner emits one of
`{pick, place, push}`; each maps to a Python skill class that builds a
target pose and plans with MoveIt. Perception is DINO+SAM with our
in-repo cleaning + sphere/cylinder/disk primitive fits.

```
RGB+depth ──► DINO ──► SAM ──► clean cloud ──► OBB / AABB / primitive
                                           │
                                           ▼
                                   Skill (pick/place/push)
                                           │
                                           ▼
                              FrankaRobot (MoveIt) ── controller: position
```

### Mode B — New paradigm (FoundationPose + TPGPT_two_args)

Under integration. FoundationPose runs on a GPU server, takes
(RGB, depth, SAM mask) and returns a 6D pose / OBB per object using a
pre-registered mesh. TPGPT_two_args runs on the robot Ubuntu, converts
poses to keypoints, records a human demo, then "transports" the demo to
new (pick, place) configurations and executes via cartesian impedance.

```
                              [robot Ubuntu]                                       [GPU server (10.72.18.159)]
RGB+depth ─► RealSense ZMQ bridge ───────────► (network) ────────────► FoundationPose docker (server_inference.py)
                                                                              │
                                                                              ▼
                                                              6D pose / labeled bbox per object (sent back)
                                                                              │
                                                                              ▼
                              keypoint_detector.py  ──►  demo_recorder.py  ──►  skill_executor.py
                                  (tpgpt-two-args)        (tpgpt-two-args)        (tpgpt-two-args)
                                                                              │
                                                                              ▼
                                                                  cartesian impedance controller
                                                                              │
                                                                              ▼
                                                                          Franka FR3
```

Differences from Mode A:

| Stage | Mode A | Mode B |
|---|---|---|
| 6D pose source | OBB/sphere/disk from cleaned cloud | FoundationPose (mesh-based) |
| Skill catalog | hardcoded `pick/place/push` | runtime `data/<skill>/` learned from human demo |
| Controller | MoveIt (`transmission:=position`) | cartesian impedance |
| Novelty | none | VLM may propose new skills; HITL demo records them |

### Switch between modes (planned)

Single config flag in `pragmabot/config/config.yaml`:

```yaml
pipeline:
  skill_mode: fixed   # fixed = Mode A | open = Mode B
```

In `open` mode the pragmabot node will additionally talk to
FoundationPose + TPGPT services (HTTP). Until that wiring lands, the
two modes run side-by-side as separate flows you launch manually.

---

## 2. Machines & repos

| Machine | Role | Repos checked out |
|---|---|---|
| **Mac** (`~/code/personal/`) | Canonical dev box. All commits originate here. | `pragmabot-repro/`, `tpgpt-two-args/`, `foundation-pose-pragmabot/` |
| **Robot Ubuntu** (`ravi@...`) | Runs ROS nodes, MoveIt, RealSense, pragmabot node, TPGPT_two_args. | `~/pragma_ws/src/pragmabot-repro/` and `~/fr3_ws/src/TPGPT_two_args/` |
| **GPU server** (`manthan@10.72.18.159`) | Runs FoundationPose docker. | `~/ssd_data/FoundationPose/` (our fork — `foundation-pose-pragmabot`) |

GitHub remotes for each clone:

- pragmabot-repro: `origin` → `<you>/pragmabot-repro` (only)
- tpgpt-two-args: `origin` → `<you>/tpgpt-two-args` (only)
- foundation-pose-pragmabot:
  - `origin` → `<you>/foundation-pose-pragmabot` (private, your work)
  - `upstream` → `NVlabs/FoundationPose` (for pulling NVlabs fixes)

---

## 3. Dev workflow — commit on Mac, pull on robot/GPU

The pattern is the same for all three repos: edit on Mac, push to
GitHub, pull on the target machine.

### Mac (canonical, all edits)

```bash
[MAC]
cd ~/code/personal/<repo>           # pragmabot-repro | tpgpt-two-args | foundation-pose-pragmabot
# edit ...
git status
git add -p                          # stage hunks interactively (safer than -A)
git commit -m "feat(<area>): <message>"
git push
```

For commits that span multiple repos, do them as separate commits in
each repo and reference the related Jira/issue in the message so they
can be traced back together.

### Robot Ubuntu (pull only)

```bash
[UBUNTU robot machine]
cd ~/pragma_ws/src/pragmabot-repro
git pull

cd ~/fr3_ws/src/TPGPT_two_args
git pull
```

For TPGPT_two_args, after pulling you may also need to rebuild the ROS
workspace if `package.xml` / `CMakeLists.txt` changed:

```bash
cd ~/fr3_ws
catkin_make            # or catkin build if that's what's in use
source devel/setup.bash
```

### GPU server (pull only)

```bash
[GPU SERVER]
ssh manthan@10.72.18.159
cd ~/ssd_data/FoundationPose
git pull origin main

# Bring in NVlabs upstream fixes when you want them:
git fetch upstream
git merge upstream/main          # resolve conflicts if any
git push origin main             # share the merged state back to your private repo
```

If FoundationPose's docker image needs rebuilding after a code change,
the README in `foundation-pose-pragmabot/` documents that — typically
not needed because `server_inference.py` is mounted into the running
container.

---

## 4. Mode A commands (current default)

Four terminals on the robot Ubuntu machine. None of these touch the GPU
server or TPGPT_two_args.

### T1 — franka_control + MoveIt

```bash
[UBUNTU]
source /opt/ros/noetic/setup.bash
source ~/fr3_ws2/devel/setup.bash
source ~/pragma_ws/devel/setup.bash
roslaunch panda_moveit_config franka_control.launch \
    robot_ip:=192.168.1.13 \
    load_gripper:=true \
    transmission:=position
```

Wait for `Ready to take commands for planning group panda_arm.`

### T2 — RealSense camera

```bash
[UBUNTU]
source /opt/ros/noetic/setup.bash
source ~/realsense_ws/devel/setup.bash
roslaunch realsense2_camera rs_aligned_depth.launch \
    align_depth:=true \
    camera:=camera_base
```

### T3 — Eye-hand TF

```bash
[UBUNTU]
source ~/fr3_ws2/devel/setup.bash
source ~/pragma_ws/devel/setup.bash
rosrun camera_calibration eye_hand_tf.py
```

### T4 — Pragmabot node

```bash
[UBUNTU]
source ~/fr3_ws2/devel/setup.bash
source ~/pragma_ws/devel/setup.bash
cd ~/pragma_ws/src/pragmabot-repro
source .venv/bin/activate
export OPENAI_API_KEY=sk-...

# One-off after T1 comes up: raise MoveIt's execution-timeout dyn params
# (they don't persist across roslaunch).
rosrun dynamic_reconfigure dynparam set /move_group/trajectory_execution \
    allowed_execution_duration_scaling 5.0
rosrun dynamic_reconfigure dynparam set /move_group/trajectory_execution \
    allowed_goal_duration_margin 10.0

# Clear any latched Franka reflex from yesterday's session.
python3 -c "
import rospy, actionlib
from franka_msgs.msg import ErrorRecoveryAction, ErrorRecoveryGoal
rospy.init_node('rec', anonymous=True, disable_signals=True)
c = actionlib.SimpleActionClient('/franka_control/error_recovery', ErrorRecoveryAction)
c.wait_for_server(rospy.Duration(5.0))
c.send_goal(ErrorRecoveryGoal())
print('recovery:', c.wait_for_result(rospy.Duration(10.0)) and c.get_state())
"

# Launch the node (kill any stale process first).
pkill -f pragmabot_node.py
PYTHONUNBUFFERED=1 python3 pragmabot/nodes/pragmabot_node.py 2>&1 | tee /tmp/pragmabot.log

# UI: http://localhost:7861
```

### Useful Mode A debug scripts

These don't touch the live pipeline; safe to run alongside T4.

```bash
# Dump per-object perception manifest (OBB/AABB/primitive + cleaning report).
PYTHONUNBUFFERED=1 python3 scripts/dump_perception_manifest.py \
    --queries "apple, plate" \
    --out /tmp/perception_manifest.json

# Per-detection 4-panel visualization (DINO bbox, SAM mask, depth+holes, OBB+AABB+primitive).
PYTHONUNBUFFERED=1 python3 scripts/visualize_perception.py \
    --queries "apple, plate" \
    --out-dir /tmp/perception_viz
xdg-open /tmp/perception_viz/index.html
```

Add `--no-base-tf` to either of those if T3 isn't up.

---

## 5. Mode B commands (FoundationPose + TPGPT_two_args)

Three machines involved. Spin up in this order, do not skip steps.

### B-1 — FoundationPose inference server (GPU)

```bash
[MAC]
ssh manthan@10.72.18.159
```

```bash
[GPU SERVER]
cd ssd_data/FoundationPose
docker exec -it foundationpose /opt/conda/envs/my/bin/python /workspace/server_inference.py
```

Leave this terminal open. The server now listens for ZMQ requests from
the robot machine.

### B-2 — Robot arm + camera + eye-hand TF (robot Ubuntu)

For **demo recording**, the arm must be in gravity-compensation so a
human can backdrive it:

```bash
[UBUNTU]
roslaunch franka_example_controllers gravity_compensation.launch \
    robot_ip:=192.168.1.12
```

Then T2 + T3 from Mode A (RealSense + eye-hand TF) in two more
terminals.

### B-3 — Stream RGB-D from robot to GPU server

A separate ROS node (`realsense_zmq_bridge.py`) reads the local
RealSense topics, sends frames via ZMQ to the GPU server, and
re-publishes the returned per-object 6D bounding boxes onto:

- `/realsense_zmq_bridge/tracking_data_base`  — labeled poses/keypoints
  in the robot base frame (subscribed by `keypoint_detector.py` and
  `skill_executor.py`).
- `/realsense_zmq_bridge/bounding_box`        — raw bbox stream
  (subscribed by `demo_keypoint_subscriber.py`).

The bridge node itself is not in this repo — it lives in a separate
ROS package alongside TPGPT_two_args on the robot machine. Run it in
its own terminal before B-4:

```bash
[UBUNTU]
# Adjust the package name once confirmed; the script name is realsense_zmq_bridge.py.
rosrun <bridge_pkg> realsense_zmq_bridge.py
```

### B-4 — Record a demo (robot Ubuntu, two terminals)

```bash
[UBUNTU]
# Terminal 1 — keypoint detector for the skill + target object(s).
rosrun TPGPT_two_args keypoint_detector.py \
    --skill pick \
    --objects mustard0 \
    --ee_pos

# Terminal 2 — demo recorder. The skill name must match.
rosrun TPGPT_two_args demo_recorder.py pick
```

Now manually guide the arm through the desired motion. The data lands in
`~/fr3_ws/src/TPGPT_two_args/data/pick/`.

To add a new skill (e.g. `pour`), use the new name in both commands.

### B-5 — Execute a known skill on a new target configuration

First switch the controller from gravity-comp to cartesian impedance.
The executor publishes equilibrium poses on
`/cartesian_impedance_example_controller/equilibrium_pose`, so this
controller (from `franka_example_controllers`) must be running:

```bash
[UBUNTU]
# Bring up the cartesian-impedance controller.
roslaunch franka_example_controllers cartesian_impedance_example_controller.launch \
    robot_ip:=192.168.1.12

# Then either rosrun the node directly...
rosrun TPGPT_two_args skill_executor.py \
    _skill_name:=pick \
    _object_name:=mustard0 \
    _data_dir:=/home/ravi/fr3_ws/src/TPGPT_two_args/data

# ...or use the launch file (defaults shown in execute_skill.launch):
roslaunch TPGPT_two_args execute_skill.launch \
    skill_name:=pick \
    object_name:=mustard0 \
    data_dir:=/home/ravi/fr3_ws/src/TPGPT_two_args/data
```

Verified: the executor generalises to new object placements as long as
the original demo had the object roughly at the recorded keypoint
location.

### Adding new objects (Mode B prerequisite)

The object's CAD mesh (`.obj`) must be registered on the GPU server's
FoundationPose database before the object name can be queried. Done by
editing files inside `~/ssd_data/FoundationPose/` and restarting the
docker.

---

## 6. Call-graph reference

Where the integration calls will live once Mode B is wired into
pragmabot:

```
pragmabot_node.py (T4 today)
  └─ PragmaBot.run_task(...)
       └─ task_planner (VLM) ─► {skill, parameters, [is_novel, novel_skill_spec]}
            │
            ├─ if known skill AND skill_mode=fixed:
            │     └─ skills/{pick,place,push}.py ─► FrankaRobot (MoveIt)
            │
            ├─ if known skill AND skill_mode=open:
            │     └─ skills/tp_gpt.py ─► HTTP POST /plan_trajectory ─► TPGPT_two_args
            │                                                      └─ cartesian impedance exec
            │
            └─ if novel skill AND skill_mode=open:
                  └─ HITL demo recorder (Gradio button)
                     ─► saves demo to data/<skill>/
                     ─► HTTP POST /train_skill on TPGPT side
                     ─► register skill in runtime skill registry
                     ─► then dispatch as if known
```

Perception side:

```
pragmabot SceneObserver
  └─ perception backend
       ├─ grounded_sam            (current — masks + our own OBB/sphere fits)
       └─ dinosam_foundationpose  (planned — DINO+SAM locally, then ZMQ to GPU FP)
            └─ DetectedObject.extras["pose_6d_camera"] = <4x4 SE(3)>
```

---

## 7. Quick reference — common operations

| I want to... | Where | Command |
|---|---|---|
| Edit pragmabot code | Mac | open `~/code/personal/pragmabot-repro/` |
| Edit TPGPT code | Mac | open `~/code/personal/tpgpt-two-args/` |
| Edit FoundationPose code | Mac | open `~/code/personal/foundation-pose-pragmabot/` |
| Run pragmabot on robot | Robot Ubuntu | T1+T2+T3+T4 above |
| Refresh code on robot | Robot Ubuntu | `cd <repo> && git pull` |
| Refresh code on GPU | GPU server | `cd ssd_data/FoundationPose && git pull origin main` |
| Pull NVlabs FP fixes | GPU server | `git fetch upstream && git merge upstream/main` |
| Inspect perception only | Robot Ubuntu | `scripts/visualize_perception.py` |
| Hand off bboxes to TP-GPT engineer | Robot Ubuntu | `scripts/dump_perception_manifest.py` |
| Switch to Mode B (future) | Mac → robot | Edit `pragmabot/config/config.yaml: pipeline.skill_mode: open` + push + pull |

---

## 8. See also

- `docs/external_systems.md` — deeper notes on the FoundationPose +
  TPGPT pipeline (API contract proposal, integration questions).
- `docs/ARCHITECTURE.md` — the pragmabot internal architecture.
- `docs/REPRODUCTION_GUIDE.md` — paper-reproduction protocol.
- `CLAUDE.md` — auto-loaded project rules at the repo root.
