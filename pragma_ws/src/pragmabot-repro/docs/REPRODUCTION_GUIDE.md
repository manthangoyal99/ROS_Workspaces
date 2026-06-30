# Reproduction Guide

Step-by-step instructions to reproduce Tables II and III from the paper.

## Hardware

- Franka Panda arm with Robotiq 2F-140 (or compatible).
- RGB-D camera — RealSense D435 or ZED X Mini.
- Ubuntu 20.04, ROS Noetic, CUDA-capable GPU.

## Software setup

See `docs/setup_ubuntu.md` for the full install (ROS Noetic, MoveIt, franka_ros,
Grounded SAM, model checkpoints).

## Reproducing Table II (STM evaluation)

### Scene setup

For each of the 4 tasks, arrange the scene as documented in
`pragmabot/src/pragmabot/eval/task_suite.py`. Tip: capture a reference RGB
frame per task and store it under `docs/scene_setup_photos/` so future
runs match.

### Run

```bash
python scripts/run_evaluation.py \
  --table table_2 \
  --conditions cap_v pragmabot \
  --n_trials 7 \
  --output_dir results/table_2_repro
```

This drives:

1. 4 tasks × 2 conditions × 7 trials = 56 trials.
2. Per-trial JSON under `results/table_2_repro/trials/`.
3. Aggregated CSV at `results/table_2_repro/aggregate/table_2_results.csv`.
4. Markdown report at `results/table_2_repro/report.md`.

### Expected (paper) values

| Task | CaP-V | PragmaBot |
|---|---|---|
| Apple on plate | ~43% | ~86% |
| Candy move | ~22% | ~67% |
| Egg move | ~40% | ~100% |
| Bowl pickup | ~33% | ~83% |

VLM non-determinism dominates variance. Set `vlm.temperature: 0.0` (already
the default) and the OpenAI `seed` parameter if available.

## Reproducing Table III (LTM evaluation)

```bash
python scripts/run_evaluation.py \
  --table table_3 \
  --conditions come pragmabot \
  --output_dir results/table_3_repro
```

12 tasks × 2 conditions × `n_trials` (5–9 per task — see `task_suite.py`).

## Known differences from the paper

1. Robot platform: Franka Panda on a fixed base, not ANYmal + arm.
2. Default VLM is `ollama:llava` (local, free); swap to `openai`
   with `vlm.model: gpt-4o-2024-08-06` for paper-comparable numbers.
3. Grasp synthesizer is `top_down` (paper uses AnyGrasp).
4. No legged locomotion — tabletop-only scenes.

## Aggregating an existing results directory without re-running

```bash
python scripts/aggregate_results.py \
  --results_dir results/table_2_repro \
  --table table_2
```
