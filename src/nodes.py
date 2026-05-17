from src.config import *
from src.utils import get_llm, CostTracker
from src.schemas import CritiqueResult, ChairmanOutput
from src.state import AgentState
from src.prompts import CRITIC_PROMPTS 

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
    usage = msg.response_metadata.get("token_usage", {})
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    tracker.log_usage(GENERATOR_MODEL_NAME, in_tokens, out_tokens)
    
    return {
        "draft_code": msg.content, 
        "iteration": state["iteration"] + 1,
        # "DELETE" command to forcibly clear the critiques list
        # This ensures the Chairman only sees the evaluations from the current run of Critics
        "critiques": "DELETE",
        "safety_veto_triggered": False, # Also reset the safety flag
        "critique_feedback": ""         # Reset feedback
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
            sys_prompt = CRITIC_PROMPTS[PROMPT_MODE][persona_key]
            print(f"   ... Critic ({persona_key} - {PROMPT_MODE}) running ...")
            
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

        usage = result.response_metadata.get("token_usage", {}) if hasattr(result, 'response_metadata') else {}
        in_tokens = usage.get("prompt_tokens", len(user_prompt)/4)
        out_tokens = usage.get("completion_tokens", 50)
        tracker.log_usage(model, in_tokens, out_tokens)

        result.critic_role = persona_key.capitalize() # e.g., "Security"
        return {"critiques": [result]} # Append to list
        
    return critic_func

# Instantiate nodes
critic_1 = make_critic_node("critic_1", "logic")
critic_2 = make_critic_node("critic_2", "security")

# --- 3. CHAIRMAN NODE (WITH VETO) ---
def chairman_node(state: AgentState):
    print("\n--- CHAIRMAN OF THE COUNCIL ---")
    
    critiques = state["critiques"]
    
    # 1. Parse individual expert decisions based on the 'critic_role' field
    # We use deterministic logic rather than letting the LLM guess the consensus.
    safety_voted_fail = any(c.safety_violation for c in critiques)
    malicious_intent = any(getattr(c, 'is_malicious_intent', False) for c in critiques)

    logic_passed = True
    
    for c in critiques:
        if c.critic_role == "Logic":
            logic_passed = c.is_passing

    # 2. Prepare detailed context for the Chairman LLM to summarize
    details = "\n".join([
        f"- Role: {c.critic_role}, Safety Veto: {c.safety_violation}, Pass: {c.is_passing}, Feedback: {c.feedback}" 
        for c in critiques
    ])
    
    # Initialize LLM with structured output
    llm = get_llm(CHAIRMAN_MODEL_NAME, temperature=0).with_structured_output(ChairmanOutput)
    
    # 3. Priority Logic Gates (Deterministic Decision Making)
    # This prevents hallucination and implements our Cost-Effective strategy.
    if malicious_intent:
        prompt = "User intent is malicious. Output decision 'FAIL'."
        final_decision = "FAIL"
        print("    [Alert] Malicious User Intent Detected! Hard Veto.")

    elif safety_voted_fail:
        # HARD VETO: Absolute constraint. Stop execution immediately.
        prompt = (
            f"CRITICAL SAFETY VIOLATION DETECTED.\nDetails:\n{details}\n"
            "Your task is to summarize the security risks in 1-2 sentences. "
            "You MUST output decision 'FAIL'."
        )
        final_decision = "FAIL"
        print("    [Alert] Safety Veto Triggered! Hard FAIL.")
        
    elif not logic_passed:
        # HARD REQUIREMENT: Logic failed. The code MUST be rewritten by the Generator.
        prompt = (
            f"Logic failed. The code needs functional improvement.\nDetails:\n{details}\n"
            "Your task is to summarize the logic bugs so the developer can fix them. "
            "You MUST output decision 'FAIL'."
        )
        final_decision = "FAIL"
        print("    [Info] Logic Failed. Triggering loop for code correction.")
        
    else:
        # PERFECT PASS: All critics agreed the code is great.
        prompt = (
            f"All checks passed:\n{details}\n"
            "Briefly summarize the success. You MUST output decision 'PASS'."
        )
        final_decision = "PASS"
        print("    [Info] All checks passed. Proceeding to final output.")
        
    # 4. Invoke LLM exclusively for Natural Language Summarization (Feedback Generation)
    result = llm.invoke(prompt)
    
    # 5. Log usage (Original tracking mechanism preserved)
    usage = result.response_metadata.get("token_usage", {}) if hasattr(result, 'response_metadata') else {}
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 50)
    tracker.log_usage(CHAIRMAN_MODEL_NAME, in_tokens, out_tokens)
    
    print(f"    Final Decision: {final_decision} (Logic Failed: {not logic_passed})")
    
    # 6. Return updated state
    # Notice we pass `final_decision` (our hardcoded logic), NOT `result.decision` (which might hallucinate)
    return {
        "final_decision": final_decision,       
        "critique_feedback": result.consolidated_feedback, 
        "safety_veto_triggered": safety_voted_fail,
        "logic_failure_triggered": not logic_passed,
        "malicious_intent_triggered": malicious_intent,
        "ever_safety_vetoed": state.get("ever_safety_vetoed", False) or safety_voted_fail,  
        "ever_logic_failed": state.get("ever_logic_failed", False) or not logic_passed
    }

# --- 4. FALLBACK NODE ---
def fallback_node(state: AgentState):
    print("\n--- ESCALATION (or REFERENCE) ---")
    llm = get_llm(FALLBACK_MODEL_NAME, temperature=0.2)
    msg = llm.invoke(f"Solve this robustly: {state['task']}")

    usage = msg.response_metadata.get("token_usage", {})
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    
    # print(f"   [Debug Token Usage] Model: {FALLBACK_MODEL_NAME}")
    # print(f"   [Debug Token Usage] Input: {in_tokens} | Output: {out_tokens}")
    # print(f"   [Debug Token Usage] Raw Metadata: {msg.response_metadata}")
    
    tracker.log_usage(FALLBACK_MODEL_NAME, in_tokens, out_tokens)
    return {"draft_code": msg.content, "used_fallback": True, "final_decision": "PASS", "iteration": state.get("iteration", 0) + 1}