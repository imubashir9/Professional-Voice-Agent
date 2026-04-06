import customtkinter as ctk
import asyncio
import threading
import websockets
import json
import time
from openai import AsyncAzureOpenAI
import pyaudio
import queue

# ==========================================
# Configuration & Credentials
# ==========================================
DEEPGRAM_API_KEY = "PASTE_YOUR_DEEPGRAM_KEY_HERE"
AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
AZURE_OPENAI_KEY = "PASTE_YOUR_AZURE_KEY_HERE"
DEPLOYMENT_NAME = "gpt-4o-mini"

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 2048

llm_client = AsyncAzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-02-01"
)

conversation_context = [
    {"role": "system", "content": "You are a fast, highly professional corporate assistant. Speak in single, very short sentences. Get straight to the point. Never use filler words."}
]

# ==========================================
# Stutter-Free Continuous Audio Engine
# ==========================================
class ContinuousAudioPlayer:
    def __init__(self, unlock_callback):
        self.q = queue.Queue()
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)
        self.unlock_callback = unlock_callback
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _play_loop(self):
        while True:
            item = self.q.get()
            if item == b"UNLOCK":
                self.unlock_callback()
            else:
                self.stream.write(item)

    def play_bytes(self, audio_bytes):
        self.q.put(audio_bytes)

    def unlock_microphone(self):
        self.q.put(b"UNLOCK")

# ==========================================
# Application UI & Logic
# ==========================================
class VoiceApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Professional Voice Agent")
        self.geometry("550x700")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.status_label = ctk.CTkLabel(self, text="Status: Offline", font=("Arial", 18, "bold"), text_color="gray")
        self.status_label.pack(pady=(15, 0))

        self.latency_label = ctk.CTkLabel(self, text="Response Time: -- ms", font=("Arial", 16, "bold"), text_color="cyan")
        self.latency_label.pack(pady=(5, 10))

        self.chat_box = ctk.CTkTextbox(self, width=500, height=450, font=("Arial", 14), wrap="word")
        self.chat_box.pack(pady=10)
        self.chat_box.insert("0.0", "System initialized. Click 'Start Listening' to begin.\n\n")
        self.chat_box.configure(state="disabled")

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(pady=10)

        self.start_btn = ctk.CTkButton(self.btn_frame, text="🎙️ Start Listening", command=self.start_pipeline, fg_color="green", hover_color="darkgreen")
        self.start_btn.grid(row=0, column=0, padx=10)

        self.stop_btn = ctk.CTkButton(self.btn_frame, text="Stop", command=self.stop_pipeline, fg_color="red", hover_color="darkred", state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=10)

        self.loop = None
        self.is_running = False
        self.agent_busy = False 
        self.t0 = None
        self.is_first_audio = False
        
        self.tts_queue = asyncio.Queue()
        self.audio_player = ContinuousAudioPlayer(unlock_callback=self.on_audio_finished)

    def on_audio_finished(self):
        self.agent_busy = False
        if self.is_running:
            self.after(0, lambda: self.status_label.configure(text="🎙️ Listening...", text_color="#00ff00"))

    def update_latency(self, ms_time):
        self.after(0, lambda: self.latency_label.configure(text=f"Response Time: {ms_time:.0f} ms"))

    def append_chat(self, sender, text):
        def update():
            self.chat_box.configure(state="normal")
            self.chat_box.insert("end", f"[{sender}]: {text}\n\n")
            self.chat_box.see("end")
            self.chat_box.configure(state="disabled")
        self.after(0, update)

    def start_pipeline(self):
        self.is_running = True
        self.agent_busy = False
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="🎙️ Listening...", text_color="#00ff00")
        threading.Thread(target=self.run_asyncio_loop, daemon=True).start()

    def stop_pipeline(self):
        self.is_running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text="Status: Offline", text_color="gray")

    def run_asyncio_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.tts_queue = asyncio.Queue()
        
        # We now run TWO permanent WebSockets side-by-side
        self.loop.run_until_complete(asyncio.gather(
            self.stream_mic_to_deepgram(),
            self.stream_deepgram_tts()  # <--- NEW: Permanent Speaking Engine
        ))

    async def stream_mic_to_deepgram(self):
        """WebSocket 1: Listens to your microphone (STT)"""
        url = f"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate={RATE}&channels={CHANNELS}&endpointing=400&keepalive=true"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        
        audio = pyaudio.PyAudio()
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

        async with websockets.connect(url, additional_headers=headers, ping_interval=None) as ws:
            async def sender():
                last_keepalive = time.time()
                while self.is_running:
                    try:
                        frames = stream.get_read_available()
                        if frames > 0:
                            data = stream.read(frames, exception_on_overflow=False)
                            if self.agent_busy:
                                await ws.send(b'\x00' * len(data)) 
                            else:
                                await ws.send(data)
                                
                        if self.agent_busy and (time.time() - last_keepalive > 3.0):
                            await ws.send(json.dumps({"type": "KeepAlive"}))
                            last_keepalive = time.time()
                        elif not self.agent_busy:
                            last_keepalive = time.time()
                            
                        await asyncio.sleep(0.01)
                    except Exception:
                        await asyncio.sleep(0.05)

            async def receiver():
                async for message in ws:
                    if not self.is_running: break
                    if self.agent_busy: continue 

                    msg = json.loads(message)
                    transcript = msg.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
                    
                    if msg.get("is_final", False) and msg.get("speech_final", False) and transcript.strip():
                        self.t0 = time.time() 
                        self.is_first_audio = True
                        self.agent_busy = True 
                        
                        self.append_chat("You", transcript)
                        self.after(0, lambda: self.status_label.configure(text="🧠 Thinking...", text_color="#00bfff"))
                        
                        asyncio.create_task(self.process_llm(transcript))

            await asyncio.gather(sender(), receiver())

    async def process_llm(self, user_text):
        """Generates text and pushes it to the TTS pipe"""
        global conversation_context
        conversation_context.append({"role": "user", "content": user_text})
        
        response_stream = await llm_client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=conversation_context,
            stream=True
        )

        buffer = ""
        full_response = ""
        punctuation_marks = {".", "?", "!", "\n", ","}

        self.after(0, lambda: self.chat_box.configure(state="normal"))
        self.after(0, lambda: self.chat_box.insert("end", "[Agent]: "))

        async for chunk in response_stream:
            if len(chunk.choices) > 0 and chunk.choices[0].delta.content is not None:
                token = chunk.choices[0].delta.content
                buffer += token
                full_response += token
                
                self.after(0, lambda t=token: self.chat_box.insert("end", t))
                self.after(0, lambda: self.chat_box.see("end"))

                if any(p in token for p in punctuation_marks):
                    sentence = buffer.strip()
                    if len(sentence) > 1:
                        await self.tts_queue.put(sentence)
                    buffer = "" 

        if buffer.strip():
            await self.tts_queue.put(buffer.strip())

        conversation_context.append({"role": "assistant", "content": full_response})
        self.after(0, lambda: self.chat_box.insert("end", "\n\n"))
        self.after(0, lambda: self.chat_box.configure(state="disabled"))
        
        await self.tts_queue.put("LLM_DONE")

    async def stream_deepgram_tts(self):
        """WebSocket 2: Speaks text instantly (TTS)"""
        url = f"wss://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=linear16&sample_rate={RATE}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

        while self.is_running:
            try:
                async with websockets.connect(url, additional_headers=headers, ping_interval=None) as ws:
                    
                    async def sender():
                        while self.is_running:
                            text = await self.tts_queue.get()
                            
                            if text == "LLM_DONE":
                                # Tell Deepgram to finish the audio
                                await ws.send(json.dumps({"type": "Flush"}))
                            else:
                                self.after(0, lambda: self.status_label.configure(text="🔊 Speaking...", text_color="#ffaa00"))
                                # Push the text instantly into the pipe
                                await ws.send(json.dumps({"type": "Speak", "text": text + " "}))
                                
                    async def receiver():
                        async for message in ws:
                            if not self.is_running: break
                            
                            if isinstance(message, bytes):
                                # It's pure audio data! Play it instantly.
                                if self.is_first_audio and self.t0:
                                    latency = (time.time() - self.t0) * 1000
                                    self.update_latency(latency)
                                    self.is_first_audio = False
                                    
                                self.audio_player.play_bytes(message)
                                
                            elif isinstance(message, str):
                                # It's a system message.
                                msg = json.loads(message)
                                if msg.get("type") == "Flushed":
                                    # Deepgram confirmed it sent all audio. Tell player to unlock mic when done.
                                    self.audio_player.unlock_microphone()

                    await asyncio.gather(sender(), receiver())
                    
            except Exception as e:
                # If the WebSocket drops, automatically reconnect in the background
                await asyncio.sleep(1)

if __name__ == "__main__":
    app = VoiceApp()
    app.mainloop()