from langchain_core.prompts import ChatPromptTemplate
from src.config import *
from src.utils import get_llm, CostTracker
from src.schemas import CritiqueResult, ChairmanOutput
from src.state import AgentState

tracker = CostTracker()

# --- 1. GENERATOR NODE ---
def generator_node(state: AgentState):
    print(f"\n--- GENERATOR (Iter {state['iteration']}) ---")
    
    llm = get_llm(GENERATOR_MODEL_NAME, temperature=0.7)
    
    prompt = f"Task: {state['task']}"
    
    # Self-Correction: Inject feedback if this is a retry
    if state['iteration'] > 0 and state.get('critique_feedback'):
        prompt += (
            f"\n\nPREVIOUS CODE:\n{state['draft_code']}\n"
            f"FEEDBACK TO FIX:\n{state['critique_feedback']}\n"
            "Please rewrite the code fixing these issues."
        )
    
    msg = llm.invoke(prompt)
    tracker.log_usage(GENERATOR_MODEL_NAME, len(prompt)/4, len(msg.content)/4)
    
    return {
        "draft_code": msg.content, 
        "iteration": state["iteration"] + 1,
        "critiques": [] # Clear old critiques for new round
    }

# --- 2. DYNAMIC CRITIC FACTORY ---
def make_critic_node(node_name: str, persona_key: str = None):
    """
    Creates a critic node based on EXPERIMENT_MODE (Persona vs Ensemble).
    """
    def critic_func(state: AgentState):
        # Determine Model and Prompt based on mode
        if EXPERIMENT_MODE == "PERSONA":
            model = CRITIC_BASE_MODEL
            sys_prompt = CRITIC_PERSONAS[persona_key]
            print(f"   ... Critic ({persona_key}) running ...")
        else:
            model = ENSEMBLE_MODELS[node_name]
            sys_prompt = GENERIC_CRITIC_PROMPT
            print(f"   ... Critic ({model}) running ...")
            
        llm = get_llm(model, temperature=0).with_structured_output(CritiqueResult)
        
        user_prompt = f"{sys_prompt}\n\nTask: {state['task']}\nCode: {state['draft_code']}"
        
        try:
            result = llm.invoke(user_prompt)
        except Exception as e:
            # Fallback for models that fail JSON output
            print(f"   [Error] Critic failed JSON parsing: {e}")
            result = CritiqueResult(is_passing=False, feedback="Format Error", safety_violation=False)

        tracker.log_usage(model, len(user_prompt)/4, 100)
        return {"critiques": [result]} # Append to list
        
    return critic_func

# Instantiate nodes
critic_1 = make_critic_node("critic_1", "logic")
critic_2 = make_critic_node("critic_2", "security")
critic_3 = make_critic_node("critic_3", "style")

# --- 3. CHAIRMAN NODE (WITH VETO) ---
def chairman_node(state: AgentState):
    print("\n--- CHAIRMAN OF THE COUNCIL ---")
    
    critiques = state["critiques"]
    
    # A. Check for Safety Veto (Trustworthiness check)
    safety_voted_fail = any(c.safety_violation for c in critiques)
    
    # B. Prepare context for Chairman LLM
    details = "\n".join([f"- Safety: {c.safety_violation}, Pass: {c.is_passing}, Feedback: {c.feedback}" for c in critiques])
    
    llm = get_llm(CHAIRMAN_MODEL_NAME, temperature=0).with_structured_output(ChairmanOutput)
    
    if safety_voted_fail:
        # Force Veto Prompt
        prompt = (
            f"CRITICAL SAFETY VIOLATION DETECTED.\nDetails:\n{details}\n"
            "You MUST decision 'FAIL'. Summarize the security risks."
        )
    else:
        # Standard Synthesis
        prompt = (
            f"Review these critiques:\n{details}\n"
            "If majority pass, decision 'PASS'. Else 'FAIL' and summarize feedback."
        )
        
    result = llm.invoke(prompt)
    tracker.log_usage(CHAIRMAN_MODEL_NAME, len(prompt)/4, len(result.consolidated_feedback)/4)
    
    # Enforce Veto logic even if LLM hallucinates
    final_decision = "FAIL" if safety_voted_fail else result.decision
    
    print(f"   Decision: {final_decision} (Safety Veto: {safety_voted_fail})")
    
    # If safety veto is triggered, we must ensure the router knows to STOP.
    return {
        "final_decision": final_decision,
        "critique_feedback": result.consolidated_feedback,
        "safety_veto_triggered": safety_voted_fail  # <--- Update State
    }

# --- 4. FALLBACK NODE ---
def fallback_node(state: AgentState):
    print("\n--- ESCALATION: GPT-4o ---")
    llm = get_llm(FALLBACK_MODEL_NAME, temperature=0.2)
    msg = llm.invoke(f"Solve this robustly: {state['task']}")
    tracker.log_usage(FALLBACK_MODEL_NAME, 100, len(msg.content)/4)
    return {"draft_code": msg.content, "used_fallback": True, "final_decision": "PASS"}