import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float


def get_config() -> Config:
    return Config(
        api_key=os.getenv("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
        model=os.getenv("MODEL", "llama-3.3-70b-versatile"),
        max_tokens=int(os.getenv("MAX_TOKENS", "512")),
        temperature=float(os.getenv("TEMPERATURE", "0.75")),
    )
