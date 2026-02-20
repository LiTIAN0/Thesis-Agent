import sys
import os
import pandas as pd
import time
from tqdm import tqdm
from datasets import load_dataset

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.graph import build_graph
from src.utils import CostTracker
from src.config import AB_MODES
from src.execution import extract_code_from_markdown, execute_humaneval_code
from run_benchmark import estimate_gpt_cost

# Path to save results
DATA_FILE = "data/ablation_detailed_robust.csv"

def load_processed_tasks(csv_path):
    """Reads completed task IDs to enable resume capability."""
    if not os.path.exists(csv_path):
        return set()
    try:
        df = pd.read_csv(csv_path)
        # Combine Mode and Task ID to prevent conflicts between different modes
        # Format: "full_system_HumanEval/10"
        return set(df["Mode"] + "_" + df["Task ID"])
    except Exception:
        return set()

def save_single_row(csv_path, row_data):
    """Appends a single row of data to the CSV."""
    df = pd.DataFrame([row_data])
    # If file doesn't exist, write Header; if exists, append without Header
    write_header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode='a', header=write_header, index=False)

def run_robust_ablation():
    # 1. Loading Full Dataset
    print("📥 Loading Full HumanEval Dataset...")
    dataset = load_dataset("openai_humaneval", split="test") # Run full dataset
    
    modes_to_run = [
        AB_MODES["BASELINE"], 
        AB_MODES["LOOP_ONLY"], 
        AB_MODES["FALLBACK_ONLY"], 
        AB_MODES["FULL_SYSTEM"]
    ]

    # 2. Check for completed tasks (Resume Logic)
    processed_keys = load_processed_tasks(DATA_FILE)
    print(f"🔄 Resuming... Found {len(processed_keys)} already completed tasks.")

    tracker = CostTracker()

    # 3. Nested Loop: Mode -> Task
    for mode in modes_to_run:
        print(f"\n=== Mode: {mode.upper()} ===")
        app = build_graph(mode=mode)
        
        for item in tqdm(dataset, desc=f"Running {mode}"):
            task_id = item["task_id"]
            
            # --- SKIP LOGIC (Skip already completed) ---
            unique_key = f"{mode}_{task_id}"
            if unique_key in processed_keys:
                continue

            # Take a break to prevent Rate Limits
            time.sleep(2) 
            
            start_time = time.time()
            cost_before = tracker.total_cost
            
            # Initialize result
            result_row = {
                "Mode": mode,
                "Task ID": task_id,
                "Success": 0,
                "Valid Success": 0,
                "Safety Veto": 0,
                "Latency (s)": 0.0,
                "Actual Cost ($)": 0.0,
                "GPT5 Baseline ($)": 0.0,
                "Savings (%)": 0.0,
                "Iterations": 0,
                "Escalated": 0,
                "Error": "" # Record error message
            }
            
            try:
                # Run Graph
                state = {
                    "task": item["prompt"], 
                    "draft_code": "", "iteration": 0, 
                    "critiques": [], "used_fallback": False,
                    "final_decision": "PASS" if mode == AB_MODES["BASELINE"] else ""
                }
                
                final_state = app.invoke(state)
                
                # Metrics
                cost_after = tracker.total_cost
                latency = time.time() - start_time
                
                actual_cost = cost_after - cost_before
                raw_code = final_state.get("draft_code", "")
                
                # Unit test
                clean_code = extract_code_from_markdown(raw_code)
                exec_success, _ = execute_humaneval_code(clean_code, item["test"], item["entry_point"])
                
                # Safety check
                safety_veto = final_state.get("safety_veto_triggered", False)
                is_valid_success = 1 if (exec_success and not safety_veto) else 0
                
                gpt5_cost = estimate_gpt_cost(item["prompt"], raw_code)
                savings = 0.0
                if gpt5_cost > 0: savings = (1 - (actual_cost / gpt5_cost)) * 100

                result_row.update({
                    "Success": 1 if exec_success else 0,
                    "Valid Success": is_valid_success,
                    "Safety Veto": 1 if safety_veto else 0,
                    "Latency (s)": round(latency, 2),
                    "Actual Cost ($)": actual_cost,
                    "GPT5 Baseline ($)": gpt5_cost,
                    "Savings (%)": round(savings, 2),
                    "Iterations": final_state.get("iteration", 0),
                    "Escalated": 1 if final_state.get("used_fallback", False) else 0
                })

            except Exception as e:
                # --- Exception Handling ---
                # Even if an error occurs, record an entry to prove this task ran (but failed)
                print(f"\n❌ Error on {task_id}: {e}")
                result_row["Error"] = str(e)[:100] # Record only first 100 characters
                # Error counts as failure, Success=0
            
            finally:
                # Write to CSV immediately, regardless of success or failure
                save_single_row(DATA_FILE, result_row)
                # Update in-memory completed list to prevent re-running without restart
                processed_keys.add(unique_key)

    print(f"\n✅ Full Ablation Complete. Results in {DATA_FILE}")

if __name__ == "__main__":
    run_robust_ablation()