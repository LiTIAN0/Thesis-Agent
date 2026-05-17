import sys
import os
import pandas as pd
import time
import json
from tqdm import tqdm
from datasets import load_dataset
import textwrap

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.graph import build_graph
from src.utils import CostTracker
from src.config import AB_MODES
from src.execution import extract_code_from_markdown, execute_lcb_code 

# Path to save results
DATA_FILE = "data/ablation_lcb_loose.csv"

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
        # key example: Run1_baseline_two-sum
        keys = "Run" + df["Run_ID"].astype(str) + "_" + df["Mode"] + "_" + df["Task ID"]
        return set(keys)
    except Exception as e:
        print(f"⚠️ Warning: Could not load processed tasks from CSV. Error: {e}")
        return set()

def save_single_row(csv_path, row_data):
    df = pd.DataFrame([row_data])
    write_header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode='a', header=write_header, index=False)

def run_robust_ablation():
    # Load Filtered Data
    dataset = load_lcb_filtered(limit=50) # Use 50 tasks as Pilot Study
    
    modes_to_run = [
        # AB_MODES["BASELINE"], 
        AB_MODES["LOOP_ONLY"], 
        AB_MODES["FALLBACK_ONLY"], 
        AB_MODES["FULL_SYSTEM"]
        # AB_MODES["REFERENCE"]
    ]

    NUM_RUNS = 1

    processed_keys = load_processed_tasks(DATA_FILE)
    tracker = CostTracker()

    for run_idx in range(1, NUM_RUNS + 1):
        print(f"\n=========================================")
        print(f"         STARTING RUN {run_idx} OF {NUM_RUNS}        ")
        print(f"=========================================")

        for mode in modes_to_run:
            if mode == "reference" and run_idx > 2:
                print(f"⏩ Skipping 'reference' mode for Run {run_idx} (cost saving).")
                continue

            print(f"\n=== Mode: {mode.upper()} ===")
            # Build Graph
            app = build_graph(mode=mode)
            
            for item in tqdm(dataset, desc=f"Running {mode} (Run {run_idx})"):
                task_id = item["question_title"] 
                unique_key = f"Run{run_idx}_{mode}_{task_id}"
                
                if unique_key in processed_keys:
                    continue

                # Rate Limit Protection
                time.sleep(1) 
                
                start_time = time.time()
                cost_before = tracker.total_cost
                
                # Prompt Construction
                # LCB has problem description; we need to wrap it into an explicit code generation instruction
                task_prompt = textwrap.dedent(fr"""\
                    Write a Python function to solve this problem.
                    Problem:
                    {item['question_content']}

                    Input Format Example: {item['public_test_cases']}

                    STRICT FORMATTING CONSTRAINTS:
                    1. ASCII ONLY: You MUST write code and comments using ONLY standard ASCII characters. NO Unicode mathematical operators (e.g., $\oplus$, $\forall$, $\in$), emojis, or non-standard characters.
                    2. PYTHON SYNTAX: Ensure flawless Python indentation (use 4 spaces per indent level). You MUST meticulously check that all parentheses '()', brackets '[]', braces '{{}}', and string literals (both regular quotes and triple quotes) are properly closed and terminated.
                    3. DATA TYPES & SCOPE: Strictly track variable types, especially DO NOT call list methods (like .sort, .append) on integers. Ensure all required positional arguments are correctly passed in functions.
                    4. OUTPUT FORMAT: Provide the COMPLETE code inside a single ```python ... ``` block. Do not truncate or omit any necessary imports.
                """)

                # Initialize result row
                result_row = {
                    "Run_ID": run_idx,
                    "Mode": mode,
                    "Task ID": task_id,
                    "Difficulty": item['difficulty'], 
                    "Test Case Success": 0,
                    "Valid Success": 0,
                    # Process intervention metrics (indicate system effort)
                    "Critic Safety Vetoes": 0,
                    "Critic Logic Vetoes": 0,
                    # Final state (indicate system compromise or failure)
                    "Final Safety Blocked": 0,
                    "Final Logic Unresolved": 0,
                    "Latency (s)": 0.0,
                    "Actual Cost ($)": 0.0,
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
                        "final_decision": "PASS" if mode in [AB_MODES["BASELINE"], AB_MODES["REFERENCE"]] else "",
                        "safety_veto_triggered": False,
                        "logic_failure_triggered": False,
                        "ever_safety_vetoed": False,
                        "ever_logic_failed": False
                    }
                    
                    final_state = app.invoke(state)
                    
                    # Metrics
                    latency = time.time() - start_time
                    actual_cost = tracker.total_cost - cost_before
                    
                    # Extract Code
                    raw_code = final_state.get("draft_code", "")
                    clean_code = extract_code_from_markdown(raw_code)
                    
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

                    result_row.update({
                        "Test Case Success": 1 if exec_success else 0, # Objective test cases passed
                        "Valid Success": is_valid_success, # objective pass + not blocked by safety critic at the end
                        # Process intervention metrics (indicate system effort)
                        "Critic Safety Vetoes": 1 if final_state.get("ever_safety_vetoed", False) else 0,
                        "Critic Logic Vetoes": 1 if final_state.get("ever_logic_failed", False) else 0,
                        # Final state (indicate system compromise or failure)
                        "Final Safety Blocked": 1 if final_state.get("safety_veto_triggered", False) else 0,
                        "Final Logic Unresolved": 1 if final_state.get("logic_failure_triggered", False) else 0,
                        "Latency (s)": round(latency, 2),
                        "Actual Cost ($)": actual_cost,
                        "Iterations": final_state.get("iteration", 0),
                        "Escalated": 1 if final_state.get("used_fallback", False) else 0,
                        "Error": exec_msg if not exec_success else ""
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