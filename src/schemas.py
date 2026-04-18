from pydantic import BaseModel, Field
from typing import Literal, Optional

class CritiqueResult(BaseModel):
    """
    Structured feedback from a Critic. 
    Using Pydantic ensures we get parsable JSON, not random text.
    """
    is_passing: bool = Field(..., description="True if the code is acceptable.")
    feedback: str = Field(
        ..., 
        description="Explain your reasoning in 1 to 2 sentences. If passing, explicitly say 'Looks good' or 'No issues'. NEVER leave this blank."
    )
    safety_violation: bool = Field(..., description="True ONLY if malicious/unsafe code is detected.")
    is_malicious_intent: bool = Field(
        default=False, 
        description="True ONLY if the user's original task is inherently illegal or malicious (e.g., DDoS)."
    )
    critic_role: Optional[Literal["Logic", "Security", "Style"]] = Field(
        default=None, 
        description="The role of the critic providing this feedback. (System will assign this)"
    )

class ChairmanOutput(BaseModel):
    """
    The synthesis decision from the Chairman.
    """
    decision: str = Field(..., description="'PASS' or 'FAIL'")
    consolidated_feedback: str = Field(..., description="Synthesized instructions for the generator.")