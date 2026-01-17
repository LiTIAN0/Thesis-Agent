import sys
import os
import pandas as pd
import time
import tiktoken
from tqdm import tqdm
from datasets import load_dataset

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.graph import build_graph
from src.utils import CostTracker
from src.execution import extract_code_from_markdown, execute_humaneval_code

# --- PRICING CONSTANTS (Per 1M Tokens) ---
# Update these based on current API prices
PRICE_GPT5 = {"input": 1.25, "output": 10.00} 

def estimate_gpt_cost(prompt: str, completion: str):
    """
    Calculates how much it WOULD cost if we used GPT-5 for this task.
    This serves as the 'Baseline' for comparison.
    """
    enc = tiktoken.encoding_for_model("gpt-5")
    in_tokens = len(enc.encode(prompt))
    out_tokens = len(enc.encode(completion))
    
    cost = (in_tokens * PRICE_GPT5["input"] / 1e6) + (out_tokens * PRICE_GPT5["output"] / 1e6)
    return cost

def run_experiment():
    print("📥 Loading Dataset (Frist 5 HumanEval tasks)...")
    dataset = load_dataset("openai_humaneval", split="test[:5]") 
    
    app = build_graph()
    results = []
    
    # Cost tracking
    tracker = CostTracker()
    initial_cost = tracker.total_cost

    for item in tqdm(dataset, desc="Benchmarking"):
        # Snapshot Cost BEFORE running
        start_total_cost = tracker.total_cost
        start_time = time.time()
        
        # Initial State
        state = {
            "task": item["prompt"],
            "draft_code": "",
            "iteration": 0,
            "critiques": [],
            "used_fallback": False,
            "final_decision": "",
            "critique_feedback": ""
        }
        
        try:
            # Run Agent
            final = app.invoke(state)
            # Snapshot Cost AFTER running
            end_total_cost = tracker.total_cost
            latency = time.time() - start_time
            
            # --- Extract Detailed Analysis Data ---
            # A. Actual Cost (Delta)
            task_actual_cost = end_total_cost - start_total_cost
            
            # B. Baseline Cost (Hypothetical GPT-5)
            raw_output = final.get("draft_code", "")

            gpt_baseline_cost = estimate_gpt_cost(item["prompt"], raw_output)
            
            # C. Cost Savings (%)
            # Avoid division by zero
            if gpt_baseline_cost > 0:
                savings = (1 - (task_actual_cost / gpt_baseline_cost)) * 100
            else:
                savings = 0.0
            
            # 1. Get Code (Truncate if too long for CSV visualization, or keep full)
            code_snippet = final.get("draft_code", "").strip()
            
            # 2. Get Chairman's final reasoning
            feedback = final.get("critique_feedback", "No feedback (Passed immediately)")
            
            # 3. Analyze Votes (Who passed, who failed?)
            # We look at the LAST round of critiques
            critiques = final.get("critiques", [])
            # Since critiques accumulate, we take the last 3 (assuming 3 critics)
            last_round_critiques = critiques[-3:] if len(critiques) >= 3 else critiques
            
            pass_count = sum(1 for c in last_round_critiques if c.is_passing)
            total_count = len(last_round_critiques)
            vote_summary = f"{pass_count}/{total_count} PASS"
            
            # 4. Safety Veto Check
            safety_triggered = any(c.safety_violation for c in last_round_critiques)
            
            # --- 1. Agent's View (Soft Metric) ---
            agent_success = final["final_decision"] == "PASS"
            
            # --- 2. Reality View (Hard Metric) ---            
            # Use robust extraction instead of simple replace
            clean_code = extract_code_from_markdown(raw_output)
            
            # Optional: Print debug info if extraction seems empty
            if not clean_code:
                print(f"⚠️ Warning: No code found in Task {item['task_id']}")
            
            # Execute !
            exec_success, exec_msg = execute_humaneval_code(
                clean_code, 
                item["test"], 
                item["entry_point"]
            )

            results.append({
                "task_id": item["task_id"],
                "agent_claimed_success": agent_success, # Did the Critic say YES?
                "actual_exec_success": exec_success,    # Did python say YES?
                #"exec_error": exec_msg,                 # If failed, why?
                #"gap": agent_success != exec_success,   # Interesting cases!
                "iterations": final["iteration"],
                "escalated": final["used_fallback"],
                "latency_sec": round(latency, 2),
                # --- THE MONEY COLUMNS ---
                "actual_cost ($)": round(task_actual_cost, 6),
                "gpt_baseline ($)": round(gpt_baseline_cost, 6),
                "savings (%)": round(savings, 2),
                "votes": vote_summary,
                "safety_veto": safety_triggered,
                "chairman_feedback": feedback    
                #"generated_code": code_snippet    
            })
            
        except Exception as e:
            print(f"❌ Error on {item['task_id']}: {e}")
            results.append({
                "task_id": item["task_id"],
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