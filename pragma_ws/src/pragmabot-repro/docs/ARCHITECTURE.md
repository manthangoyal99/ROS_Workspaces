# Architecture

## Component diagram

```
                    +----------------------+
                    |     pragmabot_node   |
                    |  (Gradio UI + ROS)   |
                    +----------+-----------+
                               |
                       PragmaBot.run_task
                               |
   +-------------+------+------+------+------+--------------+
   |             |             |             |              |
   v             v             v             v              v
SceneObserver  VLM        Perception     Memory          Robot
(ROS topic)   (stub|     (stub|grounded   (LTM CSV +     (stub|
              ollama|    _sam)             .npy + STM     franka_ros
              openai)                       in-memory)    + MoveIt)
                |                                          |
                +-> VLMSceneDescriber                      +-> Grasp synth
                +-> VLMTaskPlanner   <-- STM, LTM, objects     (top_down |
                +-> VLMSuccessDetector                          anygrasp)
                +-> VLMExperienceSummarizer                +-> Workspace
                                                              limit check
```

Selection between concrete backends happens in `config.yaml`. The global
`pragmabot.registry.registry` maps `(component_type, name) → class`, and
each factory consults the registry, so adding a backend is a one-line
`@registry.register` decoration (see `docs/EXTENSION_GUIDE.md`).

## Data flow (one pipeline step)

1. `SceneObserver.get_latest_rgb()` → image (H×W×3).
2. `VLMSceneDescriber.describe(image, instruction)` → `scene_text`.
3. `MemoryManager.retrieve(scenario_key, top_k)` → `ltm_entries`.
4. `BasePerception.detect(image, queries)` → `PerceptionResult`.
5. `VLMTaskPlanner.plan(instruction, image, stm, ltm_entries, detected_objects)`
   → action dict.
6. *(optional)* `ImageAnnotator.annotate_candidates()` → annotated image;
   `VLMTaskPlanner.plan(annotated_image)` → refined action.
7. `BaseRobot.execute_skill(skill, params, perception_result)` → `bool`.
8. `SceneObserver.get_latest_rgb()` → after image.
9. `VLMSuccessDetector.evaluate(instruction, action, before, after)`
   → feedback dict.
10. `ShortTermMemory.append(action, feedback)`.
11. *(if task complete)* `VLMExperienceSummarizer.summarize(stm)` → text;
    `MemoryManager.store(scenario_key, experience)`.

## Phase layout

- **Phase 0** — pure-Python core (config, VLM, embeddings, memory, pipeline skeleton).
- **Phase 1** — STM + four VLM modules + full Algorithm 1.
- **Phase 2** — ROS Noetic wrapping (nodes, Gradio UI, rosbag replay).
- **Phase 3** — perception (Grounded SAM + camera intrinsics + annotator).
- **Phase 4** — Franka execution (MoveIt + pluggable grasp + workspace safety).
- **Phase 5** — system integration (callbacks, episode logger, streaming UI).
- **Phase 6** — evaluation harness (Tables II / III, conditions, CSVs, report).
- **Phase 7** — research scaffolding (registry, baselines, ablations, docs).

## Extension points

Each numbered step is pluggable via the registry. See
`docs/EXTENSION_GUIDE.md` for swap recipes.
