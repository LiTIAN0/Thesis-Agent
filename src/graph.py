from langgraph.graph import StateGraph, END
from src.state import AgentState
from src.config import MAX_RETRIES, AB_MODES
from src.nodes import (
    generator_node, chairman_node, fallback_node,
    critic_1, critic_2, critic_3
)

# Default to FULL_SYSTEM if no mode is provided
DEFAULT_MODE = AB_MODES["FULL_SYSTEM"]

def get_router_logic(mode: str):
    """
    Returns the routing logic based on the selected mode.
    This dictates whether we Loop, Fail, or Escalate.
    """
    def router(state: AgentState):
        decision = state.get("final_decision", "FAIL")
        iteration = state.get("iteration", 0)
        safety_triggered = state.get("safety_veto_triggered", False)

        # --- 1. BASELINE MODE (One-Shot) ---
        if mode == AB_MODES["BASELINE"]:
            return "end"

        # --- 2. SUCCESS CONDITION ---
        if decision == "PASS":
            return "success"
        
        # --- 3. SAFETY VETO LOGIC ---
        # If unsafe, we try to fix locally (Loop), but NEVER escalate to GPT-5.
        if safety_triggered:
            # Only retry if we are in a mode that supports looping
            if mode in [AB_MODES["LOOP_ONLY"], AB_MODES["FULL_SYSTEM"]]:
                if iteration < MAX_RETRIES:
                    print("   [ROUTER] ⚠️ Safety Issue detected. Retrying locally to fix...")
                    return "retry"
            # If max retries reached OR mode doesn't support loop -> Hard Stop
            print("   [ROUTER] 🛑 Safety Veto Persists. Max retries reached. Hard Stop (No Escalation).")
            return "end" 

        # --- 4. LOGIC/STYLE ERROR ROUTING ---
        
        # Mode: LOOP_ONLY (Retry locally, then give up)
        if mode == AB_MODES["LOOP_ONLY"]:
            if iteration < MAX_RETRIES:
                return "retry"
            return "end"

        # Mode: FALLBACK_ONLY (No retry, immediate escalation)
        if mode == AB_MODES["FALLBACK_ONLY"]:
            return "escalate"

        # Mode: FULL_SYSTEM (Retry first, then Escalate)
        if mode == AB_MODES["FULL_SYSTEM"]:
            if iteration < MAX_RETRIES:
                return "retry"
            return "escalate"

        return "end"

    return router

def build_graph(mode: str = DEFAULT_MODE):
    """
    Builds the execution graph.
    Supports both 'run_benchmark.py' (detailed tracing) and 'run_ablation.py' (modes).
    """
    workflow = StateGraph(AgentState)

    # --- Add Nodes ---
    workflow.add_node("generator", generator_node)
    
    # Baseline: Simple Linear Path
    if mode == AB_MODES["BASELINE"]:
        workflow.set_entry_point("generator")
        workflow.add_edge("generator", END)
        return workflow.compile()

    # Complex Modes: Add Council
    workflow.add_node("critic_logic", critic_1)
    workflow.add_node("critic_security", critic_2)
    workflow.add_node("critic_style", critic_3)
    workflow.add_node("chairman", chairman_node)
    
    # Add Fallback only if mode supports it
    if mode in [AB_MODES["FALLBACK_ONLY"], AB_MODES["FULL_SYSTEM"]]:
        workflow.add_node("fallback", fallback_node)

    # --- Define Edges ---
    workflow.set_entry_point("generator")

    # Fan-out (Parallel Critics)
    workflow.add_edge("generator", "critic_logic")
    workflow.add_edge("generator", "critic_security")
    workflow.add_edge("generator", "critic_style")

    # Fan-in (Aggregation)
    workflow.add_edge("critic_logic", "chairman")
    workflow.add_edge("critic_security", "chairman")
    workflow.add_edge("critic_style", "chairman")

    # --- Conditional Routing ---
    # Define the map based on what the router returns
    router_map = {
        "success": END, 
        "end": END
    }
    
    # Only add 'retry' path if the nodes exist in this mode
    if mode in [AB_MODES["LOOP_ONLY"], AB_MODES["FULL_SYSTEM"]]:
        router_map["retry"] = "generator"
        
    # Only add 'escalate' path if fallback node exists
    if mode in [AB_MODES["FALLBACK_ONLY"], AB_MODES["FULL_SYSTEM"]]:
        router_map["escalate"] = "fallback"

    workflow.add_conditional_edges(
        "chairman",
        get_router_logic(mode),
        router_map
    )

    # Connect Fallback to End
    if mode in [AB_MODES["FALLBACK_ONLY"], AB_MODES["FULL_SYSTEM"]]:
        workflow.add_edge("fallback", END)

    return workflow.compile()