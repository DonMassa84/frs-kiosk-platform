#!/usr/bin/env python3
"""
AI Learning Assistant (LernMate)

Uses local LLMs to provide personalized explanations about course content.
Supports multiple backends:
- Local GPU (qwen2.5-coder:14b, fast)
- i7 Server (nemotron-3-nano, qwen2.5:3b)
- Cloud (Mistral, Groq)
"""

import json
import httpx
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AssistantConfig:
    """Configuration for AI assistant backends."""
    local_gpu_url: str = "http://127.0.0.1:11434"
    i7_url: str = "http://127.0.0.1:11438"  # Via SSH tunnel
    cloud_api: str = "mistral"  # mistral, groq, openrouter
    default_model: str = "qwen2.5:3b"
    timeout: int = 30


class AILearningAssistant:
    """
    AI-powered learning assistant that answers questions about course content.
    """
    
    def __init__(self, config: AssistantConfig = None, db=None):
        self.config = config or AssistantConfig()
        self.db = db
        
        # Model selection by use case
        self.models = {
            "explain": "qwen2.5-coder:14b",      # Local GPU - detailed explanations
            "quick": "nemotron-3-nano",           # i7 - fast responses
            "german": "qwen3:8b",                 # Local GPU - German language
            "cloud": "mistral-large-latest",      # Mistral API
            "fallback": "qwen2.5:3b"              # i7 fallback
        }
    
    async def ask(self, 
                  question: str, 
                  context: Optional[str] = None,
                  card_id: Optional[int] = None,
                  backend: str = "auto") -> Dict:
        """
        Ask a question about learning content.
        
        Args:
            question: The user's question
            context: Additional context (e.g., transcript excerpt)
            card_id: Related learning card ID
            backend: "local_gpu", "i7", "cloud", or "auto"
        """
        # Get context from database if card_id provided
        if card_id and self.db:
            card_context = await self._get_card_context(card_id)
            if card_context:
                context = (context or "") + "\n\n" + card_context
        
        # Build prompt
        system_prompt = """Du bist LernMate, ein hilfreicher KI-Lernassistent für IHK-Prüfungsvorbereitung.

Deine Aufgaben:
- Erkläre komplexe Konzepte einfach und verständlich
- Gib praktische Beispiele aus dem Projektmanagement
- Beziehe dich auf den Kursinhalt (Transkripte)
- Antworte immer auf Deutsch
- Sei ermutigend und strukturiert

Wenn du etwas nicht weißt, sage es ehrlich."""
        
        user_prompt = f"""Kontext aus dem Kurs:
{context[:2000] if context else '(Kein spezifischer Kontext)'}

Frage: {question}

Bitte gib eine hilfreiche, strukturierte Antwort:"""
        
        # Select backend and model
        model, url = await self._select_backend(backend)
        
        logger.info(f"Asking {model} via {url}: {question[:50]}...")
        
        try:
            answer = await self._call_llm(url, model, system_prompt, user_prompt)
            
            return {
                "question": question,
                "answer": answer,
                "model": model,
                "backend": url,
                "context_used": bool(context),
                "card_id": card_id
            }
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Try fallback
            if backend != "fallback":
                logger.info("Trying fallback...")
                return await self.ask(question, context, card_id, backend="fallback")
            return {
                "question": question,
                "answer": f"Entschuldigung, ich kann gerade nicht antworten. Fehler: {str(e)[:100]}",
                "error": str(e)
            }
    
    async def explain_concept(self, concept: str, difficulty: str = "einfach") -> Dict:
        """Get a detailed explanation of a concept."""
        difficulty_map = {
            "einfach": "Erkläre es wie für einen Anfänger (einfach, Alltagsbeispiele)",
            "mittel": "Erkläre es für jemanden mit Grundwissen (fachlich, aber verständlich)",
            "experte": "Erkläre es für einen Experten (detailliert, Fachbegriffe, Zusammenhänge)"
        }
        
        prompt = f"""{difficulty_map.get(difficulty, difficulty_map['einfach'])}

Konzept: {concept}

Struktiere deine Antwort:
1. Definition (1 Satz)
2. Wichtige Punkte (3-5 Stichpunkte)
3. Praxisbeispiel
4. Typische Prüfungsfrage"""
        
        return await self.ask(prompt, backend="local_gpu")
    
    async def generate_quiz_question(self, topic: str, difficulty: int = 1) -> Dict:
        """Generate a quiz question on a topic."""
        prompt = f"""Erstelle eine Multiple-Choice Prüfungsfrage zum Thema "{topic}".

Schwierigkeit: {difficulty}/5

Format:
FRAGE: [Die Frage]
A) [Antwort A]
B) [Antwort B]
C) [Antwort C]
D) [Antwort D]
RICHTIG: [A/B/C/D]
ERKLAERUNG: [Warum ist das richtig?]

Antworte NUR in diesem Format, nichts anderes."""
        
        result = await self.ask(prompt, backend="local_gpu")
        return self._parse_quiz_response(result.get("answer", ""))
    
    async def summarize_transcript(self, video_id: int, max_length: int = 200) -> Dict:
        """Summarize a video transcript."""
        if not self.db:
            return {"error": "No database connection"}
        
        # Get transcript
        cursor = await self.db.conn.execute(
            "SELECT content FROM transcripts WHERE video_id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"error": "Transcript not found"}
        
        content = row['content'][:8000]  # Limit context
        
        prompt = f"""Fasse folgenden Unterrichts-Transkript zusammen (max {max_length} Wörter):

{content}

Struktur:
- Hauptthema (1 Satz)
- 3-5 wichtige Punkte
- Schlüsselbegriffe (für Lernkarten)
- Mögliche Prüfungsfragen (2 Stück)"""
        
        return await self.ask(prompt, backend="local_gpu")
    
    async def _select_backend(self, backend: str) -> tuple:
        """Select LLM backend and model."""
        backends = {
            "local_gpu": (self.models["explain"], self.config.local_gpu_url),
            "i7": (self.models["quick"], self.config.i7_url),
            "cloud": (self.models["cloud"], "mistral"),
            "fallback": (self.models["fallback"], self.config.i7_url),
            "auto": (self.models["explain"], self.config.local_gpu_url)
        }
        
        # Test backend availability
        for b in [backend] if backend != "auto" else ["local_gpu", "i7", "cloud"]:
            url = backends.get(b, backends["auto"])[1]
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    if b == "cloud":
                        continue  # Cloud handled separately
                    r = await client.get(f"{url}/api/tags")
                    if r.status_code == 200:
                        return backends.get(b, backends["auto"])
            except:
                continue
        
        return backends["fallback"]
    
    async def _call_llm(self, url: str, model: str, system: str, user: str) -> str:
        """Call Ollama LLM."""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            r = await client.post(
                f"{url}/api/generate",
                json={
                    "model": model,
                    "prompt": user,
                    "system": system,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 500
                    }
                }
            )
            r.raise_for_status()
            return r.json().get("response", "")
    
    async def _get_card_context(self, card_id: int) -> Optional[str]:
        """Get context from a learning card."""
        if not self.db:
            return None
        cursor = await self.db.conn.execute("""
            SELECT lc.question, lc.answer, v.theme, v.lecturer, t.content
            FROM learning_cards lc
            LEFT JOIN videos v ON lc.video_id = v.id
            LEFT JOIN transcripts t ON t.video_id = v.id
            WHERE lc.id = ?
        """, (card_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return f"Thema: {row['theme']}, Dozent: {row['lecturer']}\n" \
               f"Frage: {row['question']}\n" \
               f"Antwort: {row['answer']}\n" \
               f"Kontext: {(row['content'] or '')[:500]}"
    
    def _parse_quiz_response(self, text: str) -> Dict:
        """Parse quiz response from LLM."""
        result = {
            "question": "",
            "options": [],
            "correct": "",
            "explanation": ""
        }
        
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("FRAGE:"):
                result["question"] = line[6:].strip()
            elif line.startswith(("A)", "B)", "C)", "D)")):
                result["options"].append(line[3:].strip())
            elif line.startswith("RICHTIG:"):
                result["correct"] = line[8:].strip()
            elif line.startswith("ERKLAERUNG:") or line.startswith("ERKLÄRUNG:"):
                result["explanation"] = line.split(":", 1)[1].strip()
        
        return result


# Standalone test
async def test():
    logging.basicConfig(level=logging.INFO)
    assistant = AILearningAssistant()
    
    # Test question
    result = await assistant.ask("Was ist ein Projekt?")
    print("Q: Was ist ein Projekt?")
    print(f"A: {result.get('answer', result.get('error'))[:300]}...")
    print(f"Model: {result.get('model')}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test())
