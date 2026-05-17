import os
from dotenv import load_dotenv

load_dotenv()

# --- API CONFIGURATION ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- ABLATION STUDY MODES ---
# MODE_BASELINE: Cheap model generates once. No Critics, No Loop, No Expensive model.
# MODE_LOOP: Cheap model + Critics. Retries locally on failure. No Expensive model.
# MODE_FALLBACK: Cheap model + Critics. If fails, immediately ask Expensive model. No local retry.
# MODE_FULL: The proposed architecture (Loop first, then Fallback).
# MODE_REFERENCE: Expensive model generates once. No Critics, No Loop.
AB_MODES = {
    "BASELINE": "baseline",
    "LOOP_ONLY": "loop_only",
    "FALLBACK_ONLY": "fallback_only",
    "FULL_SYSTEM": "full_system",
    "REFERENCE": "reference"
}

# Config for Retries
MAX_RETRIES = 2

# --- EXPERIMENT SETTINGS ---
# Mode "PERSONA": One model with different prompts (Thesis Core)
# Mode "ENSEMBLE": Different models with generic prompt (Comparison Study)
EXPERIMENT_MODE = "PERSONA" 

# --- MODEL NAMES ---
# Generator: The worker (Cheap/Fast)
GENERATOR_MODEL_NAME = "gpt-4.1-nano" #"nvidia/nemotron-3-nano-30b-a3b:free"

# Fallback: The expert (Expensive)
FALLBACK_MODEL_NAME = "o3-mini" #"nvidia/nemotron-3-nano-30b-a3b:free"

# Chairman: Needs to be smart to synthesize feedback
CHAIRMAN_MODEL_NAME = "gpt-4.1-nano" #"nvidia/nemotron-3-nano-30b-a3b:free" # or "meta-llama/llama-3-70b-instruct"

# --- CRITIC CONFIGURATION ---
# Base model for PERSONA mode
CRITIC_BASE_MODEL = "gpt-4.1-nano" #"nvidia/nemotron-3-nano-30b-a3b:free"

# Models for ENSEMBLE mode
ENSEMBLE_MODELS = {
    "critic_1": "mistralai/devstral-2512:free",
    "critic_2": "qwen/qwen3-coder:free"
    # "critic_3": "google/gemma-3-27b-it:free"
}

# --- PROMPTS (THE CONSTITUTION) ---
PROMPT_MODE = "NORMAL"

GENERIC_CRITIC_PROMPT = "You are a code reviewer. Check for logic, safety, and style issues."

