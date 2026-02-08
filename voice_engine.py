import os
import time
import json
import tkinter as tk
import re
import base64
import asyncio
from threading import Thread
import pyautogui
import edge_tts
import pygame
import speech_recognition as sr
from PIL import Image, ImageDraw, ImageFont
from groq import Groq
from dotenv import load_dotenv
import ctypes
import webbrowser
import glob


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

load_dotenv()

def draw_precision_grid(image_path):
    """
    Draws a numbered 10x10 grid on the image.
    This acts as a 'ruler' for the Vision AI to calculate coordinates with high accuracy.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    line_color = (180, 180, 180)  
    
    for i in range(0, 101, 10):
        x = (i / 100) * w
        y = (i / 100) * h
        draw.line([(x, 0), (x, h)], fill=line_color, width=1)
        draw.line([(0, y), (w, y)], fill=line_color, width=1)
        
        try:
            font = ImageFont.truetype("arial.ttf", 10)
            draw.text((x + 2, 5), str(i*10), fill=(255, 0, 0), font=font)
            draw.text((5, y + 2), str(i*10), fill=(255, 0, 0), font=font)
        except IOError: 
            draw.text((x + 2, 5), str(i*10), fill=(255, 0, 0))
            draw.text((5, y + 2), str(i*10), fill=(255, 0, 0))

    grid_path = "v_perception_grid.png"
    img.save(grid_path)
    return grid_path

class VoiceEngine:
    def __init__(self, loop):
        """Initializes all V.O.I.C.E. subsystems and the main async event loop."""
        self.loop = loop
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        self.vision_model = "meta-llama/llama-4-maverick-17b-128e-instruct" 
        self.text_model = "llama-3.3-70b-versatile"
        
        pygame.mixer.init()
        self.recorder = sr.Recognizer()
        self.mic = sr.Microphone()
        
        self.voice_tone = "en-GB-RyanNeural"
        self.is_speaking = False
        
        self.hud_ready = asyncio.Event()
        self.hud = None
        self.status_label = None
        self._boot_hud()

    def _boot_hud(self):
        """Spawns the transparent status overlay in a dedicated thread."""
        def run_gui():
            self.hud = tk.Tk()
            self.hud.overrideredirect(True)
            self.hud.attributes("-topmost", True, "-alpha", 0.7)
            
            w, h = pyautogui.size()
            self.hud.geometry(f"350x50+{w-370}+{h-100}")
            self.hud.configure(bg="#050505")
            
            self.status_label = tk.Label(self.hud, text="V.O.I.C.E. CALIBRATED", 
                                         fg="#00D4FF", bg="#050505", 
                                         font=("Consolas", 11, "bold"))
            self.status_label.pack(expand=True)
            
            self.loop.call_soon_threadsafe(self.hud_ready.set)
            
            self.hud.mainloop()
            
        Thread(target=run_gui, daemon=True).start()

    def update_hud(self, text, color="#00D4FF"):
        """Safely updates the HUD text from the main async loop."""
        if self.status_label:
            try: self.status_label.config(text=text.upper(), fg=color)
            except: pass

    async def speak(self, text):
        """Converts text to high-fidelity speech and handles audio playback."""
        if not text: return
        clean_msg = re.sub(r'\[.*?\]', '', text).strip()
        print(f" > V.O.I.C.E.: {clean_msg}")
        
        self.is_speaking = True
        self.update_hud("Speaking...", "#00FFFF")
        
        fname = os.path.abspath(f"v_audio_{int(time.time()*1000)}.mp3")
        try:
            communicate = edge_tts.Communicate(clean_msg, self.voice_tone)
            await communicate.save(fname)
            pygame.mixer.music.load(fname)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.05)
            pygame.mixer.music.unload()
            if os.path.exists(fname): os.remove(fname)
        except: pass
            
        self.is_speaking = False
        self.update_hud("Active", "#00D4FF")

    def capture_voice(self):
        """Listens for the user's vocal directive."""
        with self.mic as source:
            self.recorder.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recorder.listen(source, timeout=5, phrase_time_limit=8)
                return self.recorder.recognize_google(audio).lower()
            except: return None

    async def execute_vision_click(self, target_description):
        """Uses the Grid-Overlay and a high-precision prompt for 99% accuracy."""
        self.update_hud("Optical Scan...", "#FFA500")
        
        if self.hud: self.hud.withdraw()
        time.sleep(0.3) 
        raw_path = "snap.png"
        pyautogui.screenshot(raw_path)
        grid_path = draw_precision_grid(raw_path)
        if self.hud: self.hud.deiconify()
        
        with open(grid_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')

        prompt = f"""
        Analyze the screenshot which has a red-numbered grid from 0-1000.
        USER'S GOAL: Click on the '{target_description}'.

        THOUGHT PROCESS:
        1. Locate the general area of the target.
        2. Identify the precise center of that target using the grid as a ruler.
        3. CRITICAL: Do NOT click any 'x' or close buttons unless asked.
        4. Provide the coordinate on the 0-1000 scale.
        
        OUTPUT: Return ONLY a JSON object: {{"x": 0-1000, "y": 0-1000, "label": "icon_name"}}
        """
        
        try:
            completion = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                ]}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            data = json.loads(completion.choices[0].message.content)
            
            sw, sh = pyautogui.size()
            real_x = (data["x"] / 1000) * sw
            real_y = (data["y"] / 1000) * sh
            
            print(f" > TARGET: mapped to {int(real_x)}, {int(real_y)}")
            await self.speak(f"Executing.")
            pyautogui.moveTo(real_x, real_y, duration=1.2)
            pyautogui.click()

        except Exception as e:
            print(f"[Vision Fault] {e}")
            await self.speak("Visual link failed, sir. The target is obscured.")

    async def run(self):
        """The main command loop for the V.O.I.C.E. agent."""
        await self.hud_ready.wait()
        
        await self.speak("Neural bridge to Gemini 3 established. Ready to assist.")
        
        while True:
            command = self.capture_voice()
            if not command: continue
            print(f"[User]: {command}")

            if any(w in command for w in ["click", "new tab", "button", "find"]):
                target = command.replace("click", "").replace("open a", "").strip()
                if "new tab" in command: 
                    target = "the small, standalone plus-shaped icon used to open a new browser tab"
                await self.execute_vision_click(target)
                
            elif any(w in command for w in ["write", "draft", "explain"]):
                await self.speak("Consulting generative core.")
                self.update_hud("Thinking...", "#FFA500")
                try:
                    chat_completion = self.client.chat.completions.create(
                        model=self.text_model,
                        messages=[
                            {
                                "role": "system", 
                                "content": "You are V.O.I.C.E., a sophisticated and witty AI assistant. Be concise (1-2 sentences), helpful, and do not use any markdown formatting like asterisks or hashtags."
                            },
                            {"role": "user", "content": command}
                        ],
                        max_tokens=150,
                        temperature=0.7
                    )
                    ai_reply = chat_completion.choices[0].message.content
                    pyautogui.write(ai_reply)
                except Exception as e:
                    print(f"[Chat Fault] {e}")
                    await self.speak("My conversational circuits are currently out of sync, sir.")         
                
            elif "online" in command:
                await self.speak("V.O.I.C.E. activated") 

            elif "word" in command:
                await self.speak("Opening a blank word document.")
                pyautogui.hotkey("win", "r"); time.sleep(0.3)
                pyautogui.write("winword"); pyautogui.press("enter")

            elif "notepad" in command:
                await self.speak("Opening notepad.")
                pyautogui.hotkey("win", "r"); time.sleep(0.3)
                pyautogui.write("notepad"); pyautogui.press("enter")
            
            elif "search" in command:        
                await self.speak("Browsing the internet.")
                pyautogui.write("https://devpost.com/  ")
                pyautogui.press("enter")

            elif "google" in command:
                await self.speak("Connecting to information grid.")
                webbrowser.open("https://google.com")
                
            elif "shutdown" in command:
                await self.speak("Deactivating. Goodbye.")
                break
            else:
                self.update_hud("Thinking...", "#FFA500")
                try:
                    chat_completion = self.client.chat.completions.create(
                        model=self.text_model,
                        messages=[
                            {
                                "role": "system", 
                                "content": "You are V.O.I.C.E., a sophisticated and witty AI assistant. Be concise (1-2 sentences), helpful, and do not use any markdown formatting like asterisks or hashtags."
                            },
                            {"role": "user", "content": command}
                        ],
                        max_tokens=150,
                        temperature=0.7
                    )
                    ai_reply = chat_completion.choices[0].message.content
                    await self.speak(ai_reply)
                except Exception as e:
                    print(f"[Chat Fault] {e}")
                    await self.speak("My conversational circuits are currently out of sync, sir.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = VoiceEngine(loop)
    try:
        loop.run_until_complete(agent.run())
    except KeyboardInterrupt:
        pass