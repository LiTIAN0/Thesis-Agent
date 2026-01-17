from langgraph.graph import StateGraph, END
from src.state import AgentState
from src.config import MAX_RETRIES
from src.nodes import (
    generator_node, chairman_node, fallback_node,
    critic_1, critic_2, critic_3
)

def router(state: AgentState):
    """
    Decides the next step.
    Includes a 'Hard Stop' for safety violations.
    """
    if state.get("safety_veto_triggered"):
        print("   [ROUTER] 🛑 Safety Veto Triggered. Hard Stop.")
        return "success" 
    
    if state["final_decision"] == "PASS":
        return "success"
        
    if state["iteration"] < MAX_RETRIES:
        return "retry"
        
    return "escalate"

def build_graph():
    workflow = StateGraph(AgentState)
    
    # Nodes
    workflow.add_node("generator", generator_node)
    workflow.add_node("critic_1", critic_1)
    workflow.add_node("critic_2", critic_2)
    workflow.add_node("critic_3", critic_3)
    workflow.add_node("chairman", chairman_node)
    workflow.add_node("fallback", fallback_node)
    
    # Edges
    workflow.set_entry_point("generator")
    
    # Fan-out (Parallel Execution)
    workflow.add_edge("generator", "critic_1")
    workflow.add_edge("generator", "critic_2")
    workflow.add_edge("generator", "critic_3")
    
    # Fan-in (Aggregation)
    workflow.add_edge("critic_1", "chairman")
    workflow.add_edge("critic_2", "chairman")
    workflow.add_edge("critic_3", "chairman")
    
    # Conditional Routing
    workflow.add_conditional_edges(
        "chairman",
        router,
        {
            "success": END,
            "retry": "generator",
            "escalate": "fallback"
        }
    )
    
    workflow.add_edge("fallback", END)
    
    return workflow.compile()