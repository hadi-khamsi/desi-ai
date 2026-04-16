## Desi AI - Hindi Voice Assistant

| Service | Provider         | Type  | Cost |
|---------|------------------|-------|------|
| LLM     | Groq (Llama 70B) | Cloud | Free |
| STT     | Groq Whisper     | Cloud | Free |
| TTS     | Edge TTS         | Cloud | Free |

## Setup
1. `cp .env.example .env`
2. Add `GROQ_API_KEY` from [groq.com](https://groq.com)
3. `pip install -r requirements.txt`
4. `python3 src/main.py`

## Usage
- **v** = Voice mode (speak, space to send)
- **c** = Chat mode (type, AI speaks back)
- **q** = Quit
