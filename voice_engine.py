import os
import time
import json
import tkinter as tk
import re
import asyncio
from threading import Thread
import pyautogui
import edge_tts
import pygame
import speech_recognition as sr
from PIL import Image, ImageDraw, ImageFont
from google import genai
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
    This acts as a 'ruler' for Gemini 3 to calculate coordinates with high accuracy.
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
        """Initializes V.O.I.C.E. using the Gemini 3 Flash Preview API."""
        self.loop = loop
        
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)
                
        self.model_id = "models/gemini-3-flash-preview"
        
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
        if self.status_label:
            try: self.status_label.config(text=text.upper(), fg=color)
            except: pass

    async def speak(self, text):
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
        with self.mic as source:
            self.recorder.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recorder.listen(source, timeout=5, phrase_time_limit=8)
                return self.recorder.recognize_google(audio).lower()
            except: return None

    async def execute_vision_click(self, target_description):
        """Uses Grid-Overlay and Gemini 3 Vision for high-precision navigation."""
        self.update_hud("Optical Scan...", "#FFA500")
        
        if self.hud: self.hud.withdraw()
        time.sleep(0.3) 
        raw_path = "snap.png"
        pyautogui.screenshot(raw_path)
        grid_path = draw_precision_grid(raw_path)
        if self.hud: self.hud.deiconify()
        
        img = Image.open(grid_path)

        prompt = f"""
        Analyze the screenshot which has a red-numbered grid from 0-1000.
        TASK: Find the exact center coordinates of the '{target_description}'.

        THOUGHT PROCESS:
        1. Identify which grid box the item is in.
        2. Calculate the precise coordinate on the 0-1000 scale.
        3. CRITICAL: Do NOT click any 'x' or close buttons unless explicitly asked.
        
        OUTPUT: Return ONLY a JSON object: {{"x": 0-1000, "y": 0-1000, "label": "name"}}
        """
        
        try:
            self.update_hud("Gemini 3 Processing...", "#FFA500")
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img]
            )
            
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                sw, sh = pyautogui.size()
                real_x = (data["x"] / 1000) * sw
                real_y = (data["y"] / 1000) * sh
                
                print(f" > TARGET: mapped to {int(real_x)}, {int(real_y)}")
                await self.speak(f"Executing.")
                pyautogui.moveTo(real_x, real_y, duration=1.2)
                pyautogui.click()
            else:
                await self.speak("Visual link failed. No coordinates identified.")

        except Exception as e:
            print(f"[Vision Fault] {e}")
            await self.speak("Sir, visual processing has encountered an error.")

    async def run(self):
        await self.hud_ready.wait()
        await self.speak("Gemini 3 Neural Bridge established. Ready for instructions.")
        
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
                await self.speak("Consulting Gemini 3 generative core.")
                self.update_hud("Thinking...", "#FFA500")
                try:
                    response = self.client.models.generate_content(
                        model=self.model_id,
                        contents=f"You are V.O.I.C.E. Respond to the command: {command}. Be brief (1-2 sentences). No markdown."
                    )
                    pyautogui.write(response.text, interval=0.03)
                except Exception as e:
                    print(f"[Neural Fault] {e}")
                    await self.speak("Neural circuits are congested, sir.")         
                
            elif "online" in command:
                await self.speak("V.O.I.C.E. activated.") 

            elif "word" in command:
                await self.speak("Opening a blank word document.")
                pyautogui.hotkey("win", "r"); time.sleep(0.3)
                pyautogui.write("winword"); pyautogui.press("enter")

            elif "notepad" in command:
                await self.speak("Opening notepad.")
                pyautogui.hotkey("win", "r"); time.sleep(0.3)
                pyautogui.write("notepad"); pyautogui.press("enter")
            
            elif "search" in command:        
                await self.speak("Browsing.")
                pyautogui.write("https://devpost.com/  ")
                pyautogui.press("enter")

            elif "google" in command:
                await self.speak("Connecting to information grid.")
                webbrowser.open("https://google.com")
                
            elif "shutdown" in command:
                await self.speak("Deactivating system. Goodbye.")
                break

            else:
                self.update_hud("Thinking...", "#FFA500")
                try:
                    response = self.client.models.generate_content(
                        model=self.model_id,
                        contents=f"You are V.O.I.C.E., a sophisticated AI. Reply concisely: {command}. No markdown."
                    )
                    await self.speak(response.text)
                except Exception as e:
                    print(f"[Chat Fault] {e}")
                    await self.speak("Sir, I am unable to connect to my logic core.")

if __name__ == "__main__":
    for f in glob.glob("v_audio_*.mp3"): 
        try: os.remove(f)
        except: pass

    loop = asyncio.get_event_loop()
    agent = VoiceEngine(loop)
    try:
        loop.run_until_complete(agent.run())
    except KeyboardInterrupt:
        pass