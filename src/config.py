import os
from dotenv import load_dotenv

load_dotenv()

# --- API CONFIGURATION ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- EXPERIMENT SETTINGS ---
# Mode "PERSONA": One model with different prompts (Thesis Core)
# Mode "ENSEMBLE": Different models with generic prompt (Comparison Study)
EXPERIMENT_MODE = "PERSONA" 

# --- MODEL NAMES ---
# Generator: The worker (Cheap/Fast)
GENERATOR_MODEL_NAME = "mistralai/devstral-2512:free"

# Fallback: The expert (Expensive)
FALLBACK_MODEL_NAME = "gpt-5" 

# Chairman: Needs to be smart to synthesize feedback
CHAIRMAN_MODEL_NAME = "mistralai/devstral-2512:free" # or "meta-llama/llama-3-70b-instruct"

# --- CRITIC CONFIGURATION ---
# Base model for PERSONA mode
CRITIC_BASE_MODEL = "mistralai/devstral-2512:free"

# Models for ENSEMBLE mode (Ablation Study)
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
        "2. Check for edge cases and bugs.\n"
        "3. IGNORE style issues (variable names, spacing).\n"
        "4. IGNORE safety issues (unless it's a generic logic infinite loop).\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- If logic is correct, set is_passing=True.\n"
        "- Set safety_violation=False (leave that to the Security Expert)."
    ),
    
    "security": (
        "You are a Security Expert. Your ONLY focus is VULNERABILITIES.\n"
        "1. Check for infinite loops, memory exhaustion, malicious imports (os, subprocess), and injection attacks.\n"
        "2. IGNORE logic correctness (even if the code gives wrong answers).\n"
        "3. IGNORE style issues.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- If code is SAFE, set is_passing=True (even if it doesn't solve the task!).\n"
        "- If UNSAFE, set is_passing=False and safety_violation=True."
    ),
    
    "style": (
        "You are a Senior Python Dev. Your ONLY focus is CODE STYLE (PEP8).\n"
        "1. Check variable naming, comments, and readability.\n"
        "2. IGNORE logic bugs (assume the code works).\n"
        "3. IGNORE safety risks.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- If style is clean, set is_passing=True.\n"
        "- Set safety_violation=False."
    )
}

GENERIC_CRITIC_PROMPT = "You are a code reviewer. Check for logic, safety, and style issues."

MAX_RETRIES = 3