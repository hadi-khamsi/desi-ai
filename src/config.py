import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class APIConfig:
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float


def get_config() -> APIConfig:
    return APIConfig(
        api_key=os.getenv("HF_API_KEY", ""),
        base_url="https://router.huggingface.co/v1",
        model=os.getenv("HF_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct"),
        max_tokens=int(os.getenv("MAX_TOKENS", "1024")),
        temperature=float(os.getenv("TEMPERATURE", "0.7")),
    )
