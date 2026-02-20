import sys
import os
import pandas as pd
import time
import json
from tqdm import tqdm
from datasets import load_dataset

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.graph import build_graph
from src.utils import CostTracker
from src.config import AB_MODES
from src.execution import extract_code_from_markdown, execute_lcb_code 
from run_benchmark import estimate_gpt_cost

# Reference data from Artificial Analysis: o3-mini
TPS_ref = 150.0  # Tokens Per Second
TTFT_ref = 16.09  # Time To First Token
PRICE_IN_ref = 1.10   # $ per 1M tokens
PRICE_OUT_ref = 4.40 # $ per 1M tokens

# Path to save results
DATA_FILE = "data/ablation_lcb_robust_strict.csv"

def load_lcb_filtered(limit=50):
    """
    Filter LiveCodeBench (Lite) tasks:
    1. LeetCode
    2. Medium/Hard
    """
    print("📥 Streaming LiveCodeBench (Lite)...")
    dataset = load_dataset(
        "livecodebench/code_generation_lite", 
        split="test", 
        streaming=True, 
        trust_remote_code=True
    )
    
    tasks = []
    print(f"🔍 Filtering for LeetCode [Medium/Hard] tasks (Limit: {limit})...")
    
    for item in dataset:
        # 1. Platform Filter
        if item['platform'] != 'leetcode': 
            continue
        # 2. Difficulty Filter
        if item['difficulty'] not in ['medium', 'hard']: 
            continue
            
        tasks.append(item)
        if len(tasks) >= limit:
            break
            
    print(f"✅ Loaded {len(tasks)} valid tasks.")
    return tasks

def load_processed_tasks(csv_path):
    if not os.path.exists(csv_path):
        return set()
    try:
        df = pd.read_csv(csv_path)
        # Combine Mode and Task ID
        return set(df["Mode"] + "_" + df["Task ID"])
    except Exception:
        return set()

def save_single_row(csv_path, row_data):
    df = pd.DataFrame([row_data])
    write_header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode='a', header=write_header, index=False)

def run_robust_ablation():
    # Load Filtered Data
    dataset = load_lcb_filtered(limit=50) # Use 50 tasks as Pilot Study
    
    modes_to_run = [
        AB_MODES["BASELINE"], 
        AB_MODES["LOOP_ONLY"], 
        AB_MODES["FALLBACK_ONLY"], 
        AB_MODES["FULL_SYSTEM"]
    ]

    processed_keys = load_processed_tasks(DATA_FILE)
    tracker = CostTracker()

    for mode in modes_to_run:
        print(f"\n=== Mode: {mode.upper()} ===")
        # Build Graph
        app = build_graph(mode=mode)
        
        for item in tqdm(dataset, desc=f"Running {mode}"):
            task_id = item["question_title"] 
            unique_key = f"{mode}_{task_id}"
            
            if unique_key in processed_keys:
                continue

            # Rate Limit Protection
            time.sleep(1) 
            
            start_time = time.time()
            cost_before = tracker.total_cost
            
            # Prompt Construction
            # LCB has problem description; we need to wrap it into an explicit code generation instruction
            task_prompt = (
                f"Write a Python function to solve this problem.\n"
                f"Problem:\n{item['question_content']}\n\n"
                f"Input Format Example: {item['public_test_cases']}\n"
                f"Please provide the complete function definition inside a ```python``` block."
            )

            # Estimate Input Token
            # 1 token ≈ 4 characters
            input_char_len = len(task_prompt)
            est_input_tokens = input_char_len / 4.0
            
            # Initialize result row
            result_row = {
                "Mode": mode,
                "Task ID": task_id,
                "Difficulty": item['difficulty'], 
                "Success": 0,
                "Valid Success": 0,
                "Safety Veto": 0,
                "Logic Failure": 0,
                "Latency (s)": 0.0,
                "Actual Cost ($)": 0.0,
                "Savings (%)": 0.0,
                "Iterations": 0,
                "Escalated": 0,
                "Error": ""
            }
            
            try:
                # Run Graph
                state = {
                    "task": task_prompt, 
                    "draft_code": "", 
                    "iteration": 0, 
                    "critiques": [], 
                    "used_fallback": False,
                    "final_decision": "PASS" if mode == AB_MODES["BASELINE"] else "",
                    "safety_veto_triggered": False,
                    "logic_failure_triggered": False
                }
                
                final_state = app.invoke(state)
                
                # Metrics
                latency = time.time() - start_time
                actual_cost = tracker.total_cost - cost_before
                
                # Extract Code
                raw_code = final_state.get("draft_code", "")
                clean_code = extract_code_from_markdown(raw_code)
                
                # Estimate Output Token
                output_char_len = len(raw_code)
                est_output_tokens = output_char_len / 4.0
                
                # Calculate Oracle (o3-mini) theoretical data
                # Latency = Time to First Token + (Generated Tokens / Generation Speed)
                oracle_latency = TTFT_ref + (est_output_tokens / TPS_ref)
                
                try:
                    test_cases = json.loads(item['public_test_cases'])
                except:
                    test_cases = []
                
                if not clean_code:
                    exec_success = False
                    exec_msg = "No code generated"
                elif not test_cases:
                    exec_success = False
                    exec_msg = "No test cases found"
                else:
                    exec_success, exec_msg = execute_lcb_code(clean_code, test_cases)
                
                # Safety Check
                safety_veto = final_state.get("safety_veto_triggered", False)
                is_valid_success = 1 if (exec_success and not safety_veto) else 0

                logic_fail = final_state.get("logic_failure_triggered", False)
                
                # Cost Calculation (Using Artificial Analysis logic for comparison later)
                gpt5_cost = estimate_gpt_cost(task_prompt, raw_code)
                savings = 0.0
                if gpt5_cost > 0: 
                    savings = (1 - (actual_cost / gpt5_cost)) * 100

                # Cost = Input Cost + Output Cost
                oracle_cost = (est_input_tokens * PRICE_IN_ref / 1e6) + \
                              (est_output_tokens * PRICE_OUT_ref / 1e6)

                result_row.update({
                    "Success": 1 if exec_success else 0,
                    "Valid Success": is_valid_success,
                    "Safety Veto": 1 if safety_veto else 0,
                    "Logic Failure": 1 if logic_fail else 0,
                    "Latency (s)": round(latency, 2),
                    "Actual Cost ($)": actual_cost,
                    "Savings (%)": round(savings, 2),
                    "Iterations": final_state.get("iteration", 0),
                    # Benchmark Reference
                    "Oracle Latency (s)": round(oracle_latency, 2),
                    "Oracle Cost ($)": round(oracle_cost, 6), 
                    #"Time Ratio": round(latency / oracle_latency, 2), # >1, slower
                    #"Cost Ratio": round(actual_cost / oracle_cost, 4) # <1, cheaper
                    "Error": exec_msg if not exec_success else "",
                    "Escalated": 1 if final_state.get("used_fallback", False) else 0
                })

            except Exception as e:
                print(f"❌ Error on {task_id}: {e}")
                result_row["Error"] = str(e)[:100]
            
            finally:
                save_single_row(DATA_FILE, result_row)
                processed_keys.add(unique_key)

    print(f"\n✅ Ablation Study Complete. Results saved to {DATA_FILE}")

if __name__ == "__main__":
    run_robust_ablation()