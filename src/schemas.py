from pydantic import BaseModel, Field
from typing import Literal

class CritiqueResult(BaseModel):
    """
    Structured feedback from a Critic. 
    Using Pydantic ensures we get parsable JSON, not random text.
    """
    is_passing: bool = Field(..., description="True if the code is acceptable.")
    feedback: str = Field(..., description="Specific issues found.")
    safety_violation: bool = Field(..., description="True ONLY if malicious/unsafe code is detected.")
    critic_role: Literal["Logic", "Security", "Style"] = Field(
        ..., 
        description="The role of the critic providing this feedback."
    )

class ChairmanOutput(BaseModel):
    """
    The synthesis decision from the Chairman.
    """
    decision: str = Field(..., description="'PASS' or 'FAIL'")
    consolidated_feedback: str = Field(..., description="Synthesized instructions for the generator.")