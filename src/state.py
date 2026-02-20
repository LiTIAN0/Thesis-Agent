from typing import TypedDict, List, Annotated, Union
from src.schemas import CritiqueResult

def reduce_critiques(left: List[CritiqueResult], right: Union[List[CritiqueResult], str]) -> List[CritiqueResult]:
    """
    Custom reduction function:
    1. If the "DELETE" command is received, clear the list (used for Generator to reset state).
    2. Otherwise, perform list appending (used for parallel aggregation of Critics).
    """
    if right == "DELETE":
        return []
    if isinstance(right, list):
        return left + right
    return left

class AgentState(TypedDict):
    """
    The shared memory of the agent workflow.
    """
    task: str                   # User input
    draft_code: str             # Current code generation
    iteration: int              # Retry counter
    
    critiques: Annotated[List[CritiqueResult], reduce_critiques]
    
    final_decision: str         # PASS/FAIL
    critique_feedback: str      # Consolidated feedback from Chairman
    used_fallback: bool         # Metric: Did we use the expensive model?
    safety_veto_triggered: bool
    logic_failure_triggered: bool