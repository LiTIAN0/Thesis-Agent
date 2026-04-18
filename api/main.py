from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import time

# Import the compiled graph
from src.graph import build_graph

# Initialize the workflow (Defaults to FULL_SYSTEM mode)
agent_workflow = build_graph()

# Initialize the FastAPI application
app = FastAPI(
    title="Cost-Aware Multi-Agent Router API",
    description="A hybrid generator-critic framework bridging lightweight loops and expensive fallback.",
    version="1.0.0"
)

# --- Schemas for API Request/Response ---

class GenerationRequest(BaseModel):
    task_id: str = Field(default="custom_task_001", description="Unique identifier for the request.")
    prompt: str = Field(..., description="The user prompt or coding task.")

class CriticDetail(BaseModel):
    """Encapsulates the feedback from an individual critic agent for observability."""
    role: str
    passed: bool
    feedback: str
    safety_violation: bool
    malicious_intent: bool

class GenerationResponse(BaseModel):
    """The final payload returned to the client."""
    task_id: str
    status: str
    final_code: str
    iterations: int
    used_fallback: bool
    safety_veto: bool
    
    # Observability data extracted from the final graph state
    chairman_summary: str = Field(..., description="The final summary from the Chairman node.")
    critic_details: List[CriticDetail] = Field(default=[], description="Detailed feedback from the last active critic loop.")
    
    latency_seconds: float

# --- API Endpoints ---

@app.post("/api/v1/generate", response_model=GenerationResponse)
async def generate_code_endpoint(request: GenerationRequest):
    """
    Receives a task prompt, triggers the Multi-Agent Generator-Critic loop, 
    and returns the final routed code alongside system observability metrics.
    """
    start_time = time.time()
    
    try:
        # Construct the initial state matching the AgentState TypedDict
        initial_state = {
            "task": request.prompt,
            "draft_code": "",
            "iteration": 0,
            "critiques": "DELETE",  # Triggers custom reducer to ensure a clean state
            "final_decision": "",
            "critique_feedback": "",
            "used_fallback": False,
            "safety_veto_triggered": False,
            "logic_failure_triggered": False,
            "malicious_intent_triggered": False
        }
        
        # Execute the LangGraph workflow synchronously
        final_state = agent_workflow.invoke(
            initial_state, 
            config={"configurable": {"thread_id": request.task_id}}
        )
        
        latency = round(time.time() - start_time, 2)
        
        # Extract detailed critic feedback from the final state
        raw_critiques = final_state.get("critiques", [])
        extracted_critics = []

        if isinstance(raw_critiques, list):
            for c in raw_critiques:
                raw_feedback = getattr(c, "feedback", "")
                if not raw_feedback or not raw_feedback.strip():
                    clean_feedback = "Approved without specific comments." if getattr(c, "is_passing", False) else "Failed without specific explanation."
                else:
                    clean_feedback = raw_feedback

                extracted_critics.append(
                    CriticDetail(
                        role=getattr(c, "critic_role", "Unknown"),
                        passed=getattr(c, "is_passing", False),
                        feedback=clean_feedback, 
                        safety_violation=getattr(c, "safety_violation", False),
                        malicious_intent=getattr(c, "is_malicious_intent", False)
                    )
                )


        # Assemble the structured response
        return GenerationResponse(
            task_id=request.task_id,
            status=final_state.get("final_decision", "UNKNOWN"),
            final_code=final_state.get("draft_code", ""),
            iterations=final_state.get("iteration", 0),
            used_fallback=final_state.get("used_fallback", False),
            safety_veto=final_state.get("safety_veto_triggered", False) or final_state.get("malicious_intent_triggered", False),
            chairman_summary=final_state.get("critique_feedback", "No summary available."),
            critic_details=extracted_critics,
            latency_seconds=latency
        )
        
    except Exception as e:
        # Prevent internal agent crashes from bringing down the web server
        raise HTTPException(status_code=500, detail=f"Agent Execution Failed: {str(e)}")

@app.get("/health")
def health_check():
    """Health probe for container orchestration (e.g., Kubernetes, Docker)."""
    return {"status": "healthy", "service": "cost-aware-agent-api"}