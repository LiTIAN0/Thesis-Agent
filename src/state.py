import operator
from typing import TypedDict, List, Annotated
from src.schemas import CritiqueResult

class AgentState(TypedDict):
    """
    The shared memory of the agent workflow.
    """
    task: str                   # User input
    draft_code: str             # Current code generation
    iteration: int              # Retry counter
    
    # [CRITICAL] operator.add allows multiple critics to write to this list in PARALLEL
    critiques: Annotated[List[CritiqueResult], operator.add]
    
    final_decision: str         # PASS/FAIL
    critique_feedback: str      # Consolidated feedback from Chairman
    used_fallback: bool         # Metric: Did we use the expensive model?
    safety_veto_triggered: bool