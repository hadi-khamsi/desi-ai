## Desi AI - Hindi Voice Tutor

| Service | Provider         | Type  | Cost |
|---------|------------------|-------|------|
| LLM     | Groq (Llama 70B) | Cloud | Free |
| STT     | Groq Whisper     | Cloud | Free |
| TTS     | Edge TTS         | Cloud | Free |
| Music   | Local MP3s       | Local | Free |

## Setup
1. `cp .env.example .env`
2. Add `GROQ_API_KEY` from [groq.com](https://groq.com)
3. `pip install -r requirements.txt`
4. `python src/main.py`

## Usage
- **v** = Voice mode (speak, space to send)
- **c** = Chat mode (type, AI speaks back)
- **q** = Quit

## TODO
- [ ] History RAG - embed past convos → retrieve relevant
- [ ] Web RAG - search triggers → filler audio → fetch → inject
- [ ] ElevenLabs - premium voice quality/speed
- [ ] Phone access - macOS shortcut / web UI / WhatsApp bot
