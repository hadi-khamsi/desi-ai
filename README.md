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

1. **History RAG (Retrieval Augmented Generation)** - conversation memory and context retrieval
2. **Web RAG** - real-time search for recent information
3. **Agentic tool use** - AI reasons and decides which tools to use
4. **Fine-tune Whisper STT (Speech-to-Text)** - improve accuracy on accent and language switching
5. **Eval framework** - measure retrieval and response quality
6. **RLHF (Reinforcement Learning from Human Feedback)** - collect preferences, optimize with DPO (Direct Preference Optimization)
7. **Monitoring** - logging, latency tracking, usage metrics
8. **ElevenLabs ($)** - streaming TTS (Text-to-Speech) for reduced latency/voice quality
9. **Private deployment** - Mac shortcut, local web UI, WhatsApp bot
10. **Public deployment** - cloud hosting with auth
11. **(Maybe) Custom voice model** - train TTS, remove ElevenLabs ($), keep it free
12. **(Maybe) Multi-agent** - multiple AI personas in conversation
