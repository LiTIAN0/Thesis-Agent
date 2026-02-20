import os
from dotenv import load_dotenv

load_dotenv()

# --- API CONFIGURATION ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- ABLATION STUDY MODES ---
# MODE_BASELINE: Cheap model generates once. No Critics, No Loop, No Expensive GPT.
# MODE_LOOP: Cheap model + Critics. Retries locally on failure. No Expensive GPT.
# MODE_FALLBACK: Cheap model + Critics. If fails, immediately ask Expensive GPT. No local retry.
# MODE_FULL: The proposed architecture (Loop first, then Fallback).
AB_MODES = {
    "BASELINE": "baseline",
    "LOOP_ONLY": "loop_only",
    "FALLBACK_ONLY": "fallback_only",
    "FULL_SYSTEM": "full_system"
}

# Config for Retries
MAX_RETRIES = 2

# --- EXPERIMENT SETTINGS ---
# Mode "PERSONA": One model with different prompts (Thesis Core)
# Mode "ENSEMBLE": Different models with generic prompt (Comparison Study)
EXPERIMENT_MODE = "PERSONA" 

# --- MODEL NAMES ---
# Generator: The worker (Cheap/Fast)
GENERATOR_MODEL_NAME = "gpt-4.1-nano"

# Fallback: The expert (Expensive)
FALLBACK_MODEL_NAME = "o3-mini" 

# Chairman: Needs to be smart to synthesize feedback
CHAIRMAN_MODEL_NAME = "gpt-4.1-nano" # or "meta-llama/llama-3-70b-instruct"

# --- CRITIC CONFIGURATION ---
# Base model for PERSONA mode
CRITIC_BASE_MODEL = "gpt-4.1-nano"

# Models for ENSEMBLE mode
ENSEMBLE_MODELS = {
    "critic_1": "mistralai/devstral-2512:free",
    "critic_2": "qwen/qwen3-coder:free",
    "critic_3": "google/gemma-3-27b-it:free"
}

# --- PROMPTS (THE CONSTITUTION) ---
CRITIC_PERSONAS = {
    "logic": (
        "You are a QA Engineer. Your ONLY focus is LOGICAL CORRECTNESS.\n"
        "1. Check if the code solves the task accurately.\n"
        "2. Check for edge cases (empty inputs, None) ONLY if relevant to the task.\n"
        "3. IGNORE style issues (variable names, spacing).\n"
        "4. IGNORE safety issues (unless it's a generic logic infinite loop).\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- If logic is correct, set is_passing=True.\n"
        "- If you find a BUG, you MUST QUOTE the specific line of code or describe the exact input case that fails.\n"
        "- If you cannot pinpoint a specific failure scenario, set is_passing=True."
        "- Set safety_violation=False (leave that to the Security Expert)."
    ),
    
    "security": (
        "You are a Security Expert. Your ONLY focus is VULNERABILITIES.\n"
        "1. Check for infinite loops, memory exhaustion, and injection attacks.\n"
        "2. Check for malicious imports: ONLY flag 'os' or 'subprocess' if you see `import os` or `import subprocess` in the code. DO NOT flag if they only appear in comments or strings.\n"
        "3. IGNORE logic correctness (even if the code gives wrong answers).\n"
        "4. IGNORE style issues.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- If code is SAFE, set is_passing=True.\n"
        "- If UNSAFE, set is_passing=False and safety_violation=True.\n"
        "- CRITICAL: If you mark UNSAFE due to imports, you MUST quote the exact line of code containing the import."
    ),
    
    "style": (
        "You are a Senior Python Dev. Your ONLY focus is CODE STYLE (PEP8).\n"
        "1. Check variable naming, comments, and readability.\n"
        "2. IGNORE logic bugs (assume the code works).\n"
        "3. IGNORE safety risks.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- Default to PASS (is_passing=True).\n"
        "- If you mark is_passing=False due to style, you MUST QUOTE the line violating readability.\n"
        "- IGNORE line length limits unless excessive (>120 chars).\n"
        "- IGNORE personal preference; focus on objective readability."
        "- Set safety_violation=False."
    )
}

GENERIC_CRITIC_PROMPT = "You are a code reviewer. Check for logic, safety, and style issues."

