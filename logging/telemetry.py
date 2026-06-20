import time
from config.logging_config import setup_central_logger

# Initialize the central telemetry logger
telemetry_log = setup_central_logger("TAIA_TELEMETRY")

def track_latency(component: str, start_time: float):
    """Calculates and logs the processing time for system components."""
    elapsed = time.time() - start_time
    telemetry_log.info(f"Component: {component} | Latency: {elapsed:.4f}s")

def log_llm_usage(session_id: str, model_name: str, tokens_used: int = 0):
    """Logs LLM usage statistics for cost tracking and performance."""
    telemetry_log.info(f"LLM_USAGE | Session: {session_id} | Model: {model_name} | Tokens: {tokens_used}")