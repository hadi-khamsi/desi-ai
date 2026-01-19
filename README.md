## Services

| Service | Provider                | Cost         |
|---------|-------------------------|--------------|
| LLM     | Groq (Llama 3.3 70B)    | Free         |
| STT     | Groq Whisper            | Free         |
| TTS     | Edge TTS / ElevenLabs   | Free / $22/mo|
| Music   | Local MP3s in `/music`  | Free         |

## Setup
1. Copy `.env.example` to `.env`
2. Add `GROQ_API_KEY` from [groq.com](https://groq.com)
3. `pip install -r requirements.txt`
4. `python src/main.py` → type `convo`

## TODO
- [ ] Web RAG - current info (search triggers → filler audio → fetch → inject)
- [ ] History RAG - conversation memory (embed past convos → retrieve relevant)
- [ ] ElevenLabs - premium voice (set TTS_PROVIDER=elevenlabs)
- [ ] Access on phone - macOS shortcut / web frontend / WhatsApp bot
