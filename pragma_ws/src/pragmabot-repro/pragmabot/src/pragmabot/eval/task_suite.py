"""Task definitions for reproducing the paper's Tables II and III."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class TaskDefinition:
    """One evaluation task as it appears in the paper's tables."""

    name: str
    instruction: str
    description: str
    success_criteria: str
    n_trials: int
    paper_table: str  # "table_2" | "table_3"
    objects_required: List[str] = field(default_factory=list)
    baseline_success_rate: float = 0.0
    pragmabot_success_rate: float = 0.0


# ---------------------------------------------------------------------------
# Table II — STM effect (4 tasks)
# ---------------------------------------------------------------------------

TABLE_2_TASKS: List[TaskDefinition] = [
    TaskDefinition(
        name="apple_on_plate_container",
        instruction="Put the apple on the plate",
        description="Apple on table, container obstructing path to plate",
        success_criteria="Apple is on the plate",
        n_trials=7,
        paper_table="table_2",
        objects_required=["apple", "plate", "container"],
        baseline_success_rate=0.43,
        pragmabot_success_rate=0.86,
    ),
    TaskDefinition(
        name="candy_move_sponge",
        instruction="Move the tiny candy to the banana",
        description="Candy on table, sponge or towel nearby as tool",
        success_criteria="Candy is touching or on banana",
        n_trials=9,
        paper_table="table_2",
        objects_required=["candy", "banana", "sponge"],
        baseline_success_rate=0.22,
        pragmabot_success_rate=0.67,
    ),
    TaskDefinition(
        name="egg_move_open",
        instruction="Move the egg to the plate",
        description="Egg on table, open view (no obstruction)",
        success_criteria="Egg is on the plate",
        n_trials=5,
        paper_table="table_2",
        objects_required=["egg", "plate"],
        baseline_success_rate=0.40,
        pragmabot_success_rate=1.00,
    ),
    TaskDefinition(
        name="bowl_pickup_apple_inside",
        instruction="Pick up the bowl",
        description="Bowl on table with apple inside",
        success_criteria="Bowl is lifted, apple handled correctly",
        n_trials=6,
        paper_table="table_2",
        objects_required=["bowl", "apple"],
        baseline_success_rate=0.33,
        pragmabot_success_rate=0.83,
    ),
]


# ---------------------------------------------------------------------------
# Table III — LTM effect (12 tasks). The first four mirror Table II scenes;
# the remaining eight are novel scenarios from the paper.
# ---------------------------------------------------------------------------

TABLE_3_TASKS: List[TaskDefinition] = [
    TaskDefinition(
        name="apple_on_plate_container",
        instruction="Put the apple on the plate",
        description="Apple on table, container obstructing path to plate",
        success_criteria="Apple is on the plate",
        n_trials=7,
        paper_table="table_3",
        objects_required=["apple", "plate", "container"],
        baseline_success_rate=0.57,
        pragmabot_success_rate=0.86,
    ),
    TaskDefinition(
        name="candy_move_sponge",
        instruction="Move the tiny candy to the banana",
        description="Candy on table, sponge or towel nearby as tool",
        success_criteria="Candy is touching or on banana",
        n_trials=9,
        paper_table="table_3",
        objects_required=["candy", "banana", "sponge"],
        baseline_success_rate=0.44,
        pragmabot_success_rate=0.78,
    ),
    TaskDefinition(
        name="egg_move_open",
        instruction="Move the egg to the plate",
        description="Egg on table, open view (no obstruction)",
        success_criteria="Egg is on the plate",
        n_trials=5,
        paper_table="table_3",
        objects_required=["egg", "plate"],
        baseline_success_rate=0.80,
        pragmabot_success_rate=1.00,
    ),
    TaskDefinition(
        name="bowl_pickup_apple_inside",
        instruction="Pick up the bowl",
        description="Bowl on table with apple inside",
        success_criteria="Bowl is lifted, apple handled correctly",
        n_trials=6,
        paper_table="table_3",
        objects_required=["bowl", "apple"],
        baseline_success_rate=0.50,
        pragmabot_success_rate=0.83,
    ),
    TaskDefinition(
        name="ball_in_box_mug",
        instruction="Put the ball in the box",
        description="Ball on table, mug in front of the box opening",
        success_criteria="Ball is inside the box",
        n_trials=6,
        paper_table="table_3",
        objects_required=["ball", "box", "mug"],
        baseline_success_rate=0.33,
        pragmabot_success_rate=0.83,
    ),
    TaskDefinition(
        name="orange_plate_fan",
        instruction="Put the orange on the plate",
        description="Orange on table, small fan blocking the plate",
        success_criteria="Orange is on the plate",
        n_trials=6,
        paper_table="table_3",
        objects_required=["orange", "plate", "fan"],
        baseline_success_rate=0.33,
        pragmabot_success_rate=0.83,
    ),
    TaskDefinition(
        name="paper_brush",
        instruction="Move the paper into the bin using the brush",
        description="Scrap of paper on table, brush nearby as a tool",
        success_criteria="Paper is in the bin",
        n_trials=6,
        paper_table="table_3",
        objects_required=["paper", "bin", "brush"],
        baseline_success_rate=0.17,
        pragmabot_success_rate=0.67,
    ),
    TaskDefinition(
        name="screw_towel",
        instruction="Pick up the screw using the towel",
        description="Screw on table, towel nearby; bare grasp not feasible",
        success_criteria="Screw is lifted via the towel",
        n_trials=6,
        paper_table="table_3",
        objects_required=["screw", "towel"],
        baseline_success_rate=0.17,
        pragmabot_success_rate=0.67,
    ),
    TaskDefinition(
        name="sushi_open",
        instruction="Pick up the sushi",
        description="Sushi piece on the table, no obstructions",
        success_criteria="Sushi is lifted from the table",
        n_trials=5,
        paper_table="table_3",
        objects_required=["sushi"],
        baseline_success_rate=0.60,
        pragmabot_success_rate=1.00,
    ),
    TaskDefinition(
        name="grape_open",
        instruction="Pick up the grape",
        description="Single grape on the table, no obstructions",
        success_criteria="Grape is lifted from the table",
        n_trials=5,
        paper_table="table_3",
        objects_required=["grape"],
        baseline_success_rate=0.40,
        pragmabot_success_rate=0.80,
    ),
    TaskDefinition(
        name="carton_apple",
        instruction="Pick up the apple in the carton",
        description="Apple inside a milk carton",
        success_criteria="Apple is lifted out of the carton",
        n_trials=6,
        paper_table="table_3",
        objects_required=["apple", "carton"],
        baseline_success_rate=0.33,
        pragmabot_success_rate=0.83,
    ),
    TaskDefinition(
        name="towel_orange",
        instruction="Push the towel near the orange",
        description="Towel on table, orange a few inches away",
        success_criteria="Towel is adjacent to the orange",
        n_trials=6,
        paper_table="table_3",
        objects_required=["towel", "orange"],
        baseline_success_rate=0.50,
        pragmabot_success_rate=1.00,
    ),
]


ALL_TASKS: List[TaskDefinition] = TABLE_2_TASKS + TABLE_3_TASKS


def get_task(name: str, table: str = "") -> TaskDefinition:
    """Look up a task by name. ``table`` disambiguates duplicate names."""
    pool: List[TaskDefinition]
    if table:
        pool = get_table_tasks(table)
    else:
        pool = ALL_TASKS
    for t in pool:
        if t.name == name:
            return t
    raise KeyError(f"unknown task {name!r}")


def get_table_tasks(table: str) -> List[TaskDefinition]:
    """Return the task list for ``"table_2"`` or ``"table_3"``."""
    if table == "table_2":
        return list(TABLE_2_TASKS)
    if table == "table_3":
        return list(TABLE_3_TASKS)
    raise ValueError(f"unknown table {table!r}; expected 'table_2' or 'table_3'")


def task_lookup_by_table() -> Dict[str, List[TaskDefinition]]:
    return {"table_2": list(TABLE_2_TASKS), "table_3": list(TABLE_3_TASKS)}
