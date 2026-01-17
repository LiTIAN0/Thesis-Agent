from langchain_openai import ChatOpenAI
from src.config import OPENAI_API_KEY, OPENROUTER_API_KEY, OPENROUTER_BASE_URL

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
            "gpt-4o": {"in": 5.00, "out": 15.00},
            "llama-3": {"in": 0.05, "out": 0.10}, # Example cheap price
            "free": {"in": 0.0, "out": 0.0}
        }
        
        # Determine rate
        key = "free" if ":free" in model_name else ("gpt-4o" if "gpt-4" in model_name else "llama-3")
        rate = prices[key]
        
        cost = (estimated_input_tokens * rate["in"] / 1e6) + (estimated_output_tokens * rate["out"] / 1e6)
        self.total_cost += cost
        # print(f"   [COST] {model_name}: +${cost:.6f}")

def get_llm(model_name: str, temperature: float = 0.7):
    """
    Factory to return the correct LLM client (OpenAI or OpenRouter).
    """
    if "gpt" in model_name.lower():
        return ChatOpenAI(api_key=OPENAI_API_KEY, model=model_name, temperature=temperature)
    else:
        return ChatOpenAI(
            api_key=OPENROUTER_API_KEY, 
            base_url=OPENROUTER_BASE_URL,
            model=model_name, 
            temperature=temperature
        )