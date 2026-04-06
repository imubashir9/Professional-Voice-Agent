# 🎙️ Professional Voice Agent

A lightning-fast, full-duplex Voice AI Agent built with Python. 

This application listens to your microphone in real-time, processes your speech using a large language model, and responds with ultra-low latency voice using a continuous audio stream.

## ✨ Features
* **Real-time Speech-to-Text:** Powered by Deepgram.
* **Low-Latency LLM:** Powered by Azure OpenAI (`gpt-4o-mini`).
* **Continuous Streaming TTS:** Custom built continuous audio player to eliminate stuttering.
* **Digital Mute & KeepAlive:** Prevents the AI from hearing its own echo and maintains a rock-solid WebSocket connection.

## 🚀 How to Run
1. Clone this repository.
2. Install the required packages: `pip install customtkinter websockets openai httpx pyaudio`
3. Add your API keys to the top of `voice-ui.py`.
4. Run the application: `python voice-ui.py`
