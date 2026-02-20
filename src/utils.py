from langchain_openai import ChatOpenAI
from src.config import OPENAI_API_KEY, OPENROUTER_API_KEY, OPENROUTER_BASE_URL
import os

class CostTracker:
    """
    Singleton to track estimated costs for the Thesis 'Cost-Efficiency' metric.
    """
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CostTracker, cls).__new__(cls)
            cls._instance.total_cost = 0.0
        return cls._instance

    def log_usage(self, model_name: str, estimated_input_tokens: int, estimated_output_tokens: int):
        # Simplified pricing table (per 1M tokens) - Update with real OpenRouter prices
        prices = {
            "expert": {"in": 1.10, "out": 4.40}, # Example expensive price: o3-mini
            "cheap": {"in": 0.1, "out": 0.4}, # Example cheap price: gpt-4.1-nano
            "free": {"in": 0.0, "out": 0.0}
        }
        
        # Determine rate
        key = "free" if ":free" in model_name else ("cheap" if "nano" in model_name else "expert")
        rate = prices[key]
        
        cost = (estimated_input_tokens * rate["in"] / 1e6) + (estimated_output_tokens * rate["out"] / 1e6)
        self.total_cost += cost
        # print(f"   [COST] {model_name}: +${cost:.6f}")


def get_llm(model_name: str, temperature: float = 0.0):
    """
    Factory to return the correct LLM client (OpenAI or OpenRouter).
    Handles parameter compatibility for GPT-5 vs older models.
    """
    
    # Define base parameters (common to all models, without 'temperature')
    params = {
        "model": model_name,
    }

    # Determine if it is a GPT-5 series / Reasoning model
    # List all new models that do not support 'temperature'
    reasoning_models = ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1-codex", "o3-mini"]
    is_reasoning_model = any(rm in model_name.lower() for rm in reasoning_models)
    
    if is_reasoning_model:
        # === For GPT-5 / High Reasoning Mode ===
        # Must remove parameters like temperature, top_p, etc.
        # Add reasoning parameters
        #params["reasoning_effort"] = "high" # Uncomment to use high reasoning
        pass
    else:
        # === For Traditional Models (GPT-4) ===
        # Retain temperature to control randomness
        params["temperature"] = temperature

    if any(x in model_name.lower() for x in ["gpt", "o1", "o3"]):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ OPENAI_API_KEY is missing in environment variables!")
            
        return ChatOpenAI(
            api_key=api_key,
            **params
        )
    else:
        # OpenRouter
        return ChatOpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url=os.environ.get("OPENROUTER_BASE_URL"),
            **params
        )