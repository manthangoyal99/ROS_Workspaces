"""Evaluation harness — reproduces Tables II and III from the paper."""

from .aggregator import ResultAggregator
from .conditions import CONDITIONS, ConditionManager
from .evaluator import EvaluationConfig, Evaluator
from .report_generator import ReportGenerator
from .task_suite import (
    ALL_TASKS,
    TABLE_2_TASKS,
    TABLE_3_TASKS,
    TaskDefinition,
    get_table_tasks,
    get_task,
)
from .trial_runner import TrialConfig, TrialResult, TrialRunner

__all__ = [
    "ALL_TASKS",
    "CONDITIONS",
    "ConditionManager",
    "EvaluationConfig",
    "Evaluator",
    "ReportGenerator",
    "ResultAggregator",
    "TABLE_2_TASKS",
    "TABLE_3_TASKS",
    "TaskDefinition",
    "TrialConfig",
    "TrialResult",
    "TrialRunner",
    "get_table_tasks",
    "get_task",
]
