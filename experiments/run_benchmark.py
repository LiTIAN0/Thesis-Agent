import sys
import os
import pandas as pd
import time
import tiktoken
from tqdm import tqdm
from langchain_core.callbacks import BaseCallbackHandler
from typing import Dict, Any, List
from uuid import UUID
import json

os.environ["HF_DATASETS_CACHE"] = "data/hf_cache" 
os.environ["HF_HOME"] = "data/hf_home" 

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.graph import build_graph
from src.utils import CostTracker
from src.execution import extract_code_from_markdown, execute_humaneval_code, execute_lcb_code
from src.reporting import RobustCaseStudyReporter

# --- LATENCY TRACKER CALLBACK ---
class LatencyTrackerCallback(BaseCallbackHandler):
    """
    A specific callback to track HOW MUCH time is spent purely on LLM API calls (Compute Time).
    This allows us to calculate: 
    1. System Overhead (Total Wall Time - LLM Compute Time)
    2. Parallelism Factor (LLM Compute Time / Total Wall Time)
    """
    def __init__(self):
        self.total_llm_time = 0.0
        self.runs = {} # Store start times for concurrent runs

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], *, run_id: UUID, **kwargs: Any) -> Any:
        # Record the start time of an LLM call
        self.runs[run_id] = time.time()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> Any:
        # Calculate duration when LLM finishes
        if run_id in self.runs:
            duration = time.time() - self.runs[run_id]
            self.total_llm_time += duration
            del self.runs[run_id]

def estimate_gpt_cost(prompt: str, completion: str):
    """
    Calculates how much it WOULD cost if we used GPT-5 for this task.
    This serves as the 'Baseline' for comparison.
    """
    # --- PRICING CONSTANTS (Per 1M Tokens) ---
    # Update these based on current API prices
    PRICE_ref = {"input": 1.10, "output": 4.40} 
    
    enc = tiktoken.encoding_for_model("o3-mini")
    in_tokens = len(enc.encode(prompt))
    out_tokens = len(enc.encode(completion))
    
    cost = (in_tokens * PRICE_ref["input"] / 1e6) + (out_tokens * PRICE_ref["output"] / 1e6)
    return cost

def format_history_trace(trace_logs: list) -> str:
    """Formats the execution steps into a readable string for the CSV."""
    summary = []
    for log in trace_logs:

        log_type = log.get("type", "")
        iteration = log.get("iter", 0)
        
        if log_type == "critic_feedback":
            feedback_snippet = log.get('content', '').replace('\n', ' ')[:30] + "..."
            summary.append(f"-> ❌ Critic: {feedback_snippet}")
            
        elif log_type == "generator_update":
            if log.get("iter") <= 1:
                summary.append("📝 Generator Created")
            else:
                summary.append(" -> 🔄 Generator Refined")
        
        elif log_type == "fallback_update":
            summary.append(f" -> 🚀 ESCALATION (o3-mini)")
                
        elif log_type == "pass":
            summary.append(" -> ✅ PASS")
            
        elif log_type == "veto":
            summary.append(" -> 🛑 SAFETY VETO")
    return "".join(summary)


from datasets import load_dataset

def load_lcb_streaming(limit=50):
    print(f"🚀 Streaming LiveCodeBench (Lite) - First {limit} LeetCode tasks...")
    
    # Key: streaming=True
    # This skips the large file download and reads data directly from the network stream
    dataset = load_dataset(
        "livecodebench/code_generation_lite", 
        split="test", 
        streaming=True,
        trust_remote_code=True
    )
    
    tasks = []
    
    for item in dataset:
        if item['platform'] != 'leetcode':
            continue
            
        if item['difficulty'] not in ['medium', 'hard']:
            continue
            
        tasks.append(item)
        print(f"✅ Found task: {item['question_title']} ({item['difficulty']})")
        
        if len(tasks) >= limit:
            break
            
    print(f"🎉 Successfully loaded {len(tasks)} tasks via streaming!")
    return tasks

def run_experiment():
    #print("📥 Loading Dataset (HumanEval tasks)...")
    #dataset = load_dataset("openai_humaneval", split="test[32:33]") 
    dataset = load_lcb_streaming(limit=1)
    
    app = build_graph()
    results = []
    
    # Cost tracking
    tracker = CostTracker()
    initial_cost = tracker.total_cost

    for item in tqdm(dataset, desc="Benchmarking"):
        latency_handler = LatencyTrackerCallback() # Reset for each task
        # Snapshot Cost BEFORE running
        start_total_cost = tracker.total_cost
        start_time = time.time()

        task_prompt = (
            f"Write a Python function to solve this:\n"
            f"{item['question_content']}\n"
            f"Input format: {item['public_test_cases']}\n" 
            f"Provide the complete function in a ```python``` block."
        )
        
        # Initial State
        state = {
            "task": task_prompt,
            "draft_code": "",
            "iteration": 0,
            "critiques": [],
            "used_fallback": False,
            "final_decision": "",
            "critique_feedback": ""
        }

        trace_logs = []
        history_snapshots = [] # Store snapshots for Case Study
        reporter = RobustCaseStudyReporter()

        # Keep track of the 'current' running state to merge partial updates
        running_state = state.copy()
        
        try:
            # === EXECUTION WITH TRACING & CALLBACKS ===
            # We use .stream() to capture the loop history
            # We pass 'latency_handler' to capture LLM timings
            for event in app.stream(state, config={"callbacks": [latency_handler]}):

                # --- 1. Handle Code Updates (Generator OR Fallback) ---
                # Check if a node updated 'draft_code'
                current_node_name = next(iter(event))
                node_output = event[current_node_name]
                
                if "draft_code" in node_output:
                    # We cannot allow the "DELETE" string to overwrite the list-type 'critiques'
                    updates = node_output.copy()
                    if updates.get("critiques") == "DELETE":
                        updates["critiques"] = [] # Force local state to an empty list
                        running_state["critiques"] = [] # Ensure running_state is reset
                        running_state["safety_veto_triggered"] = False
                        running_state["critique_feedback"] = ""

                    # Update running state
                    running_state.update(node_output)
                    
                    # Distinguish between Generator and Fallback
                    is_fallback = "fallback" in current_node_name or node_output.get("used_fallback", False)
                    
                    # Create Snapshot
                    snapshot_iter = "Fallback (GPT-5)" if is_fallback else running_state.get("iteration", 0)

                    current_code = extract_code_from_markdown(node_output.get("draft_code", ""))
                    
                    history_snapshots.append({
                        "iter": snapshot_iter,
                        "draft_code": current_code,
                        "critiques": [],
                        "feedback": ""   
                    })
                    
                    log_type = "fallback_update" if is_fallback else "generator_update"
                    current_iter = running_state.get("iteration", 0)
                    trace_logs.append({"type": log_type, "iter": current_iter})

                # 2. Handle Critics (Accumulate Critiques)
                # Check for any node outputting 'critiques' (logic, security, style)
                for node_name, node_output in event.items():
                    if "critiques" in node_output:
                    
                        new_critiques = node_output["critiques"]
                        # If this is the "DELETE" signal emitted by the Generator, skip concatenation
                        if new_critiques == "DELETE":
                            continue

                        # Update running state
                        existing = running_state.get("critiques", [])
                        # Ensure 'existing' is a list (to prevent initialization issues)
                        if not isinstance(existing, list): existing = []
                        running_state["critiques"] = existing + new_critiques

                        
                        # Update the CURRENT snapshot with these new critiques
                        if history_snapshots:
                            history_snapshots[-1]["critiques"].extend(new_critiques)

                # 3. Capture Chairman Feedback (The 'Cause')
                if "chairman" in event:
                    chair_node = event["chairman"]
                    # Update running state
                    running_state.update(chair_node)
                    decision = chair_node.get("final_decision")
                    feedback = chair_node.get("critique_feedback", "")
                    
                    # Link feedback to the PREVIOUS code snapshot (which triggered it)
                    if history_snapshots:
                        history_snapshots[-1]["feedback"] = feedback

                    # Check for safety veto
                    if chair_node.get("safety_veto_triggered", False):
                         trace_logs.append({"type": "veto"})
                    
                    if decision == "FAIL":
                        trace_logs.append({
                            "iter": running_state.get("iteration"),
                            "type": "critic_feedback",
                            "content": feedback
                        })
                    elif decision == "PASS":
                        trace_logs.append({"type": "pass"})
                    
            # Snapshot Cost AFTER running
            end_total_cost = tracker.total_cost
            
            # --- Extract Detailed Analysis Data ---
            # Latency Breakdown
            total_latency = time.time() - start_time
            llm_latency = latency_handler.total_llm_time

            # A. Actual Cost (Delta)
            task_actual_cost = end_total_cost - start_total_cost
            
            # B. Baseline Cost (Hypothetical GPT-5)
            raw_output = running_state.get("draft_code", "")
            gpt_baseline_cost = estimate_gpt_cost(task_prompt, raw_output)
            
            # C. Cost Savings (%)
            # Avoid division by zero
            if gpt_baseline_cost > 0:
                savings = (1 - (task_actual_cost / gpt_baseline_cost)) * 100
            else:
                savings = 0.0
            
            # 1. Get Code (Truncate if too long for CSV visualization, or keep full)
            #code_snippet = running_state.get("draft_code", "").strip()
            
            # 2. Get Chairman's final reasoning
            # feedback = running_state.get("critique_feedback", "No feedback (Passed immediately)")
            
            # 3. Analyze Votes (Who passed, who failed?)
            # We look at the LAST round of critiques
            critiques = running_state.get("critiques", [])
            # Since critiques accumulate, we take the last 3 (assuming 3 critics)
            last_round_critiques = critiques[-3:] if len(critiques) >= 3 else critiques
            
            pass_count = sum(1 for c in last_round_critiques if c.is_passing)
            total_count = len(last_round_critiques)
            final_vote = f"{pass_count}/{total_count} PASS"
            
            # 4. Safety Veto Check
            safety_triggered = any(c.safety_violation for c in last_round_critiques)
            
            # --- 1. Agent's View (Soft Metric) ---
            agent_success = running_state["final_decision"] == "PASS"
            # If Fallback, the Agent defaults to assuming success (since it is a strong model)
            if running_state.get("used_fallback", False):
                agent_success = True
            
            # --- 2. Reality View (Hard Metric) ---            
            # Use robust extraction instead of simple replace
            clean_code = extract_code_from_markdown(raw_output)
            
            # Optional: Print debug info if extraction seems empty
            if not clean_code:
                print(f"⚠️ Warning: No code found in Task {item['task_id']}")

            test_cases = json.loads(item['public_test_cases'])
            if clean_code:
                exec_success, exec_msg = execute_lcb_code(clean_code, test_cases)
            else:
                exec_success, exec_msg = False, "No code generated"

            # Loop Effectiveness
            # Did it fail first, retry, and then succeed?
            #was_corrected = (running_state.get("iteration", 0) > 1) and (running_state.get("final_decision") == "PASS")

            # Decide whether to generate a Case Study report
            # Condition A: A Loop occurred (iteration > 1) -> proves architecture effectiveness / analyze side effects
            has_loop = len(history_snapshots) > 1
            
            # Condition B: Inconsistent results (Agent says OK, Python says No) -> analyze hallucination/misjudgment
            has_discrepancy = agent_success and not exec_success
            
            # Condition C: Safety interception occurred (Safety Veto) -> analyze safety
            
            # Generate report if any condition is met
            if has_loop or has_discrepancy or safety_triggered:
                report_metrics = {
                    "exec_success": exec_success,
                    "exec_error": exec_msg, # Write error info into the report for easier troubleshooting
                    "agent_claimed_success": agent_success
                }
                reporter.save_report(item['question_title'], task_prompt, history_snapshots, metrics=report_metrics)

            results.append({
                "task_id": item['question_title'],
                "agent_claimed_success": agent_success, # Did the Critic say YES?
                "actual_exec_success": exec_success,    # Did python say YES?
                #"exec_error": exec_msg,                 # If failed, why?
                #"gap": agent_success != exec_success,   # Interesting cases!
                # Loop Metrics
                "iterations": running_state.get("iteration", 0),
                #"was_corrected": was_corrected,
                "trace_history": format_history_trace(trace_logs),
                "escalated": running_state.get("used_fallback", False),
                # Latency Breakdown
                "total_latency (s)": round(total_latency, 2),
                "llm_latency (s)": round(llm_latency, 2),
                "llm_time_share (%)": round((llm_latency / total_latency * 100), 1) if total_latency > 0 else 0,
                # --- THE MONEY COLUMNS ---
                "actual_cost ($)": round(task_actual_cost, 6),
                "gpt_baseline ($)": round(gpt_baseline_cost, 6),
                "savings (%)": round(savings, 2),
                "final_votes": final_vote,
                "safety_veto": safety_triggered,
                #"chairman_feedback": feedback    
                #"generated_code": code_snippet    
            })
            
        except Exception as e:
            print(f"❌ Error on {item['question_title']}: {e}")
            results.append({
                "task_id": item['question_title'],
                "error": str(e)
            })

    # Generate Report
    os.makedirs("data", exist_ok=True)
    df = pd.DataFrame(results)
    
    # Save to CSV
    csv_path = "data/benchmark_results.csv"
    df.to_csv(csv_path, index=False)
    
    session_cost = tracker.total_cost - initial_cost
    print(f"\n✅ Benchmarking Complete!")
    print(f"Total Session Cost: ${session_cost:.4f}")
    print(f"Report saved to: {csv_path}")

if __name__ == "__main__":
    run_experiment()