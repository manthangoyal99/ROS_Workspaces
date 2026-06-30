# Extension Guide

Every pluggable component in PragmaBot lives behind an abstract base class
and is selected from `config.yaml`. The global `registry` (in
`pragmabot/src/pragmabot/registry.py`) maps `(component_type, backend_name)`
pairs to classes; factories defer to the registry, so adding a backend
never requires editing a factory.

## Adding a new VLM backend

1. Create `pragmabot/src/pragmabot/vlm/my_vlm.py`:

   ```python
   from pragmabot.registry import registry
   from pragmabot.vlm.base import BaseVLM

   @registry.register("vlm", "my_vlm")
   class MyVLM(BaseVLM):
       def chat(self, messages): ...
       def chat_with_image(self, messages, images): ...
       @property
       def backend_name(self): return "my_vlm"
   ```

2. Import once at startup — add to `_register_defaults()` in
   `registry.py` or import your module from
   `pragmabot/src/pragmabot/__init__.py` so the decorator fires.

3. Use via config:

   ```yaml
   vlm:
     backend: my_vlm
   ```

No other files need to change.

## Adding a new memory strategy

The memory system is split into two interfaces:

- `BaseEmbedder` — text → vector.
- `MemoryManager` — store / retrieve / RAG.

To swap retrieval strategy (e.g. MMR instead of cosine similarity):

1. Subclass `MemoryManager` and override `retrieve()`.
2. Register: `registry.register("memory", "mmr")(MMRMemoryManager)`.
3. Wire it into `PragmaBot.__init__` when `memory.backend == "mmr"`.

## Adding a new grasp synthesizer

1. Subclass `BaseGraspSynthesizer` in `robot/grasp/my_grasp.py`.
2. Register: `@registry.register("grasp", "my_grasp")`.
3. Set `robot.grasp.backend: my_grasp` in config.

`FrankaRobot` consumes whatever the synthesizer returns via
`filter_by_ik` + `_pose_from_matrix`.

## Adding a new skill

To add a skill beyond pick / place / push:

1. Add an abstract method to `BaseRobot`:
   `def execute_my_skill(self, ...) -> bool`.
2. Implement in `StubRobot` (log the call).
3. Implement in `FrankaRobot` with the workspace-limit check.
4. Add to `execute_skill()` dispatch (in `BaseRobot`).
5. Add the skill to `pipeline.available_skills` in `config.yaml`.

## Adding a novel planning strategy

To replace or augment `VLMTaskPlanner`:

1. Create a class with the same `plan()` signature.
2. Register: `@registry.register("planner", "my_planner")`.
3. Wire into `PragmaBot.__init__` (currently hardcoded to
   `VLMTaskPlanner`; promote to registry lookup if you need this).

## Running an ablation

```bash
python scripts/run_ablation.py \
  --sweep memory.top_k 1 3 5 \
  --tasks table_2 --n_trials 3 \
  --output_dir results/ablation_top_k --stub
```

## Suggested novel directions (paper §VI)

1. **MMR-based retrieval** vs cosine similarity — sweep
   `memory.retrieval_strategy: [cosine, mmr]`.
2. **Multi-modal memory keys** — implement a CLIP embedder and set
   `embeddings.backend: clip`.
3. **Memory pruning** — subclass `MemoryManager` with LRU/relevance decay.
4. **Tactile feedback** — augment `VLMSuccessDetector` with FCI force data.
5. **Shared / federated LTM** across robot instances.
