#!/usr/bin/env python3
"""
AI Learning Assistant - Simple Version (curl-based, no httpx dependency)
"""

import json
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AssistantConfig:
    local_gpu_url: str = "http://127.0.0.1:11434"
    i7_url: str = "http://127.0.0.1:11438"  # Via SSH tunnel or direct
    timeout: int = 60

class SimpleAIAssistant:
    """AI Assistant using curl (no external dependencies)."""
    
    def __init__(self, config: AssistantConfig = None, db=None):
        self.config = config or AssistantConfig()
        self.db = db
        
        self.models = {
            "fast": "nemotron-3-nano:latest",
            "german": "qwen2.5:3b",
            "quality": "qwen2.5-coder-7b:latest",
            "vision": "llava:7b"
        }
    
    def ask(self, question: str, context: str = None, backend: str = "auto") -> Dict:
        """Ask a question using curl."""
        # Build prompt
        system_prompt = "Du bist LernMate, ein hilfreicher KI-Lernassistent für IHK-Prüfungsvorbereitung. Antworte immer auf Deutsch, strukturiert und ermutigend."
        
        user_prompt = f"""Kontext: {context[:1000] if context else 'Allgemeines Wissen'}

Frage: {question}

Antwort:"""
        
        # Select model and URL
        model = self.models.get("german", "qwen2.5:3b")
        url = self.config.local_gpu_url
        
        if backend == "i7":
            url = self.config.i7_url
            model = self.models["fast"]
        
        logger.info(f"Asking {model} via {url}")
        
        # Call via curl
        payload = json.dumps({
            "model": model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 500}
        })
        
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", f"{url}/api/generate",
                 "-H", "Content-Type: application/json",
                 "-d", payload,
                 "-m", str(self.config.timeout)],
                capture_output=True, text=True, timeout=self.config.timeout + 5
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {
                    "question": question,
                    "answer": data.get("response", ""),
                    "model": model,
                    "backend": url
                }
            else:
                return {"error": f"curl failed: {result.stderr}"}
                
        except Exception as e:
            return {"error": str(e)}
    
    def explain(self, concept: str, difficulty: str = "einfach") -> Dict:
        prompt = f"""Erkläre das Konzept '{concept}' für die IHK-Prüfung ({difficulty}).
Struktur: 1. Definition (1 Satz), 2. Wichtige Punkte (3 Stichpunkte), 3. Praxisbeispiel, 4. Typische Prüfungsfrage."""
        return self.ask(prompt)
    
    def generate_quiz(self, topic: str) -> Dict:
        prompt = f"""Erstelle eine Multiple-Choice Frage zum Thema '{topic}'.
Format:
FRAGE: ...
A) ...
B) ...
C) ...
D) ...
RICHTIG: A/B/C/D
ERKLAERUNG: ..."""
        return self.ask(prompt)

# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ai = SimpleAIAssistant()
    result = ai.ask("Was ist ein Projekt?", backend="i7")
    print("Q: Was ist ein Projekt?")
    print(f"A: {result.get('answer', result.get('error'))[:200]}...")
