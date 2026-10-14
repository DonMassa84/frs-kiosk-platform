#!/usr/bin/env python3
"""
FRS Archive & Kiosk Platform V2 - Best Practices API

Features:
- Async FastAPI with aiosqlite
- FTS5 with bm25() ranking
- Leitner box spaced repetition
- Query caching
- Improved kiosk UX endpoints
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.database_v2 import CourseDatabaseV2

app = FastAPI(
    title="FRS Archive & Kiosk Platform V2",
    description="Best Practices Edition with async, caching, and Leitner spaced repetition",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database instance
db = CourseDatabaseV2()

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class ReviewRequest(BaseModel):
    correct: bool
    user_id: str = "default"


@app.on_event("startup")
async def startup():
    await db.connect()


@app.on_event("shutdown")
async def shutdown():
    await db.close()


# ============ FRS Archive Endpoints (Async) ============

@app.get("/api/v2/search")
async def search_v2(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100)
):
    """Full-text search with bm25() ranking and caching."""
    results = await db.search_transcripts(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/v2/videos")
async def get_videos_v2(
    lecturer: Optional[str] = None,
    theme: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """Get videos with async database."""
    sql = "SELECT * FROM videos WHERE 1=1"
    params = []
    if lecturer:
        sql += " AND lecturer = ?"
        params.append(lecturer)
    if theme:
        sql += " AND theme = ?"
        params.append(theme)
    sql += " ORDER BY date DESC LIMIT ?"
    params.append(limit)
    
    cursor = await db.conn.execute(sql, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ============ Kiosk V2 Endpoints (Leitner System) ============

@app.get("/api/v2/kiosk/review")
async def get_review_cards(
    user_id: str = "default",
    limit: int = Query(20, le=100)
):
    """Get cards due for review (Leitner system)."""
    return await db.get_cards_for_review(user_id=user_id, limit=limit)


@app.post("/api/v2/kiosk/review/{card_id}")
async def review_card_v2(card_id: int, review: ReviewRequest):
    """Submit card review with Leitner box algorithm."""
    result = await db.review_card(card_id, review.correct, review.user_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/v2/kiosk/stats")
async def get_kiosk_stats_v2(user_id: str = "default"):
    """Get learning statistics with Leitner box distribution."""
    return await db.get_learning_stats(user_id=user_id)


@app.get("/api/v2/kiosk/quiz")
async def get_quiz_v2(count: int = Query(10, le=50), user_id: str = "default"):
    """Get random cards for quiz mode."""
    cursor = await db.conn.execute("""
        SELECT lc.*, v.filename, v.theme, v.lecturer
        FROM learning_cards lc
        LEFT JOIN videos v ON lc.video_id = v.id
        ORDER BY RANDOM() LIMIT ?
    """, (count,))
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ============ Dashboard V2 ============

@app.get("/api/v2/dashboard")
async def get_dashboard_v2(user_id: str = "default"):
    """Enhanced dashboard with Leitner statistics."""
    stats = await db.get_learning_stats(user_id)
    
    # Cards due today by box
    cursor = await db.conn.execute("""
        SELECT leitner_box, COUNT(*) as count 
        FROM learning_cards 
        WHERE next_review <= datetime('now', '+1 day')
        GROUP BY leitner_box
    """)
    due_by_box = {row['leitner_box']: row['count'] for row in await cursor.fetchall()}
    
    # Recent activity (last 7 days)
    cursor = await db.conn.execute("""
        SELECT session_date, 
               SUM(correct_count) as correct, 
               SUM(incorrect_count) as incorrect
        FROM user_sessions 
        WHERE session_date >= date('now', '-7 days')
        GROUP BY session_date 
        ORDER BY session_date
    """)
    recent_activity = [dict(r) for r in await cursor.fetchall()]
    
    return {
        "leitner_stats": stats,
        "due_by_box": due_by_box,
        "recent_activity": recent_activity,
        "recommendations": _get_recommendations(stats)
    }


def _get_recommendations(stats: Dict) -> List[str]:
    """Generate personalized recommendations based on learning stats."""
    recs = []
    box_dist = stats.get("box_distribution", {})
    
    if stats.get("due_for_review", 0) > 10:
        recs.append(f"📚 {stats['due_for_review']} Karten warten auf Wiederholung - starte eine Session!")
    
    if box_dist.get("box_1_new", 0) > 20:
        recs.append("🎯 Viele neue Karten - konzentriere dich auf das Lernen statt Wiederholen")
    
    if stats.get("mastery_percent", 0) > 50:
        recs.append("🏆 Über 50% gemeistert - großartige Leistung!")
    
    if stats.get("average_streak", 0) < 2:
        recs.append("💪 Arbeite an längeren Lern-Serien für bessere Retention")
    
    return recs or ["🎓 Bereit zum Lernen! Starte eine Session."]


# ============ Frontend Routes ============

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html><head><title>FRS Platform V2</title>
    <style>
        body { font-family: system-ui; max-width: 800px; margin: 50px auto; padding: 20px; }
        .card { background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 10px 0; }
        .badge { background: #28a745; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; }
    </style></head>
    <body>
        <h1>🚀 FRS Archive & Kiosk Platform <span class="badge">V2</span></h1>
        <p><strong>Neu in V2:</strong> Async API, Leitner Spaced Repetition, Query Caching, bm25() Ranking</p>
        <div class="card"><h2>📻 FRS Archiv</h2><a href="/frs">→ Öffnen</a></div>
        <div class="card"><h2>🎓 Lern-Kiosk V2</h2><a href="/kiosk-v2">→ Öffnen (Leitner System)</a></div>
        <div class="card"><h2>📊 Dashboard V2</h2><a href="/dashboard-v2">→ Öffnen</a></div>
        <div class="card"><h2>📖 API Docs</h2><a href="/docs">→ OpenAPI</a></div>
    </body></html>
    """


@app.get("/kiosk-v2", response_class=HTMLResponse)
async def kiosk_v2():
    """V2 Kiosk with improved UX (WCAG 2.2, large touch targets, animations)."""
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IHK Kiosk V2 - Leitner System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: system-ui; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            min-height: 100vh;
            /* WCAG 2.2: High contrast background */
        }
        header { background: rgba(0,0,0,0.3); color: white; padding: 1rem 2rem; }
        
        .container { max-width: 900px; margin: 0 auto; padding: 2rem; }
        
        /* WCAG 2.2: Large touch targets (min 48x48px, we use 64px) */
        .btn { 
            min-height: 64px; 
            min-width: 120px;
            font-size: 1.25rem;
            border: none; 
            border-radius: 12px; 
            cursor: pointer;
            transition: all 0.2s;
            /* Instant feedback (Best Practice) */
        }
        .btn:active { transform: scale(0.95); }
        
        .btn-correct { background: #2ecc71; color: white; }
        .btn-wrong { background: #e74c3c; color: white; }
        .btn-show { background: #3498db; color: white; width: 100%; }
        
        /* Leitner Box Visual */
        .leitner-boxes { display: flex; gap: 0.5rem; margin-bottom: 2rem; }
        .leitner-box { 
            flex: 1; 
            height: 80px;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            transition: all 0.3s;
        }
        .leitner-box.active { transform: scale(1.1); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .box-1 { background: #e74c3c; }
        .box-2 { background: #e67e22; }
        .box-3 { background: #f1c40f; }
        .box-4 { background: #3498db; }
        .box-5 { background: #2ecc71; }
        
        .card { 
            background: white; 
            border-radius: 16px; 
            padding: 2rem;
            min-height: 400px;
            /* WCAG 2.2: Clear visual hierarchy */
        }
        .question { font-size: 1.5rem; color: #2c3e50; margin-bottom: 1.5rem; }
        .answer { 
            font-size: 1.25rem; 
            color: #27ae60; 
            padding: 1.5rem;
            background: #f0fff4; 
            border-radius: 8px;
            display: none;
            animation: fadeIn 0.3s; /* Instant feedback */
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .stats { display: flex; gap: 1rem; margin-bottom: 2rem; }
        .stat { 
            background: rgba(255,255,255,0.2); 
            padding: 1rem; 
            border-radius: 8px;
            color: white;
            text-align: center;
            flex: 1;
        }
        .stat .number { font-size: 2rem; font-weight: bold; }
        
        .feedback {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 5rem;
            animation: pop 0.5s;
            pointer-events: none;
            z-index: 1000;
        }
        @keyframes pop {
            0% { transform: translate(-50%, -50%) scale(0); }
            50% { transform: translate(-50%, -50%) scale(1.5); }
            100% { transform: translate(-50%, -50%) scale(1); opacity: 0; }
        }
        
        .progress-ring {
            width: 120px;
            height: 120px;
            margin: 0 auto;
        }
    </style>
</head>
<body>
    <header>
        <h1>🎓 IHK Kiosk V2 <small>Leitner System</small></h1>
        <a href="/" style="color: white;">← Zurück</a>
    </header>
    
    <div class="container">
        <!-- Leitner Box Visualization -->
        <div class="leitner-boxes" id="leitnerBoxes">
            <div class="leitner-box box-1" data-box="1"><span>Box 1</span><span id="box1count">-</span></div>
            <div class="leitner-box box-2" data-box="2"><span>Box 2</span><span id="box2count">-</span></div>
            <div class="leitner-box box-3" data-box="3"><span>Box 3</span><span id="box3count">-</span></div>
            <div class="leitner-box box-4" data-box="4"><span>Box 4</span><span id="box4count">-</span></div>
            <div class="leitner-box box-5" data-box="5"><span>🏆 Box 5</span><span id="box5count">-</span></div>
        </div>
        
        <div class="stats">
            <div class="stat"><div class="number" id="dueNow">-</div><div>Heute fällig</div></div>
            <div class="stat"><div class="number" id="mastery">-</div><div>% Gemeistert</div></div>
            <div class="stat"><div class="number" id="streak">-</div><div>Ø Serie</div></div>
        </div>
        
        <div class="card" id="card">
            <div class="question" id="question">Lade Karten...</div>
            <div class="answer" id="answer"></div>
            <div style="margin-top: 2rem;">
                <button class="btn btn-show" onclick="showAnswer()">Antwort zeigen</button>
            </div>
        </div>
        
        <div id="actionButtons" style="display: none; gap: 1rem; margin-top: 1rem;">
            <button class="btn btn-correct" onclick="review(true)">✓ Richtig</button>
            <button class="btn btn-wrong" onclick="review(false)">✗ Falsch</button>
        </div>
        
        <div id="feedback" class="feedback" style="display: none;"></div>
    </div>

    <script>
        const API = '/api/v2/kiosk';
        let cards = [];
        let currentIndex = 0;
        let currentCard = null;
        
        // Haptic feedback (Best Practice: multi-sensory feedback)
        function vibrate(pattern = [50]) {
            if (navigator.vibrate) navigator.vibrate(pattern);
        }
        
        function showFeedback(correct) {
            const fb = document.getElementById('feedback');
            fb.textContent = correct ? '✓' : '✗';
            fb.style.color = correct ? '#2ecc71' : '#e74c3c';
            fb.style.display = 'block';
            vibrate(correct ? [50, 50, 100] : [100, 50, 100]);
            setTimeout(() => fb.style.display = 'none', 500);
        }
        
        async function loadStats() {
            const res = await fetch(API + '/stats');
            const stats = await res.json();
            
            const dist = stats.box_distribution;
            document.getElementById('box1count').textContent = dist.box_1_new;
            document.getElementById('box2count').textContent = dist.box_2_learning;
            document.getElementById('box3count').textContent = dist.box_3_learning;
            document.getElementById('box4count').textContent = dist.box_4_review;
            document.getElementById('box5count').textContent = dist.box_5_mastered;
            
            document.getElementById('dueNow').textContent = stats.due_for_review;
            document.getElementById('mastery').textContent = stats.mastery_percent + '%';
            document.getElementById('streak').textContent = stats.average_streak;
        }
        
        async function loadCards() {
            const res = await fetch(API + '/review?limit=50');
            cards = await res.json();
            currentIndex = 0;
            if (cards.length > 0) showCard();
            else document.getElementById('question').textContent = '🎉 Keine Karten fällig! Gut gemacht!';
        }
        
        function showCard() {
            if (currentIndex >= cards.length) {
                document.getElementById('question').innerHTML = '🎉 <strong>Session abgeschlossen!</strong><br><button class="btn btn-show" onclick="loadCards()" style="margin-top: 1rem;">Neue Session</button>';
                document.getElementById('actionButtons').style.display = 'none';
                return;
            }
            
            currentCard = cards[currentIndex];
            document.getElementById('question').textContent = currentCard.question;
            document.getElementById('answer').textContent = currentCard.answer;
            document.getElementById('answer').style.display = 'none';
            document.querySelector('.card button').style.display = 'block';
            document.getElementById('actionButtons').style.display = 'none';
            
            // Highlight current box (Best Practice: visual feedback)
            document.querySelectorAll('.leitner-box').forEach(b => b.classList.remove('active'));
            document.querySelector(`.leitner-box[data-box="${currentCard.leitner_box}"]`).classList.add('active');
        }
        
        function showAnswer() {
            document.getElementById('answer').style.display = 'block';
            document.querySelector('.card button').style.display = 'none';
            document.getElementById('actionButtons').style.display = 'flex';
            vibrate([30]);
        }
        
        async function review(correct) {
            showFeedback(correct);
            
            await fetch(API + '/review/' + currentCard.id, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({correct: correct})
            });
            
            loadStats();
            currentIndex++;
            setTimeout(showCard, 300);
        }
        
        loadStats();
        loadCards();
    </script>
</body>
</html>
    """)


@app.get("/dashboard-v2", response_class=HTMLResponse)
async def dashboard_v2():
    return HTMLResponse("""
<!DOCTYPE html>
<html><head><title>Dashboard V2</title>
<style>
    body { font-family: system-ui; max-width: 1000px; margin: 50px auto; padding: 20px; }
    .card { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 10px 0; }
    .rec { background: #e8f4f8; padding: 10px; border-radius: 4px; margin: 5px 0; }
</style></head>
<body>
    <h1>📊 Dashboard V2 - Leitner System</h1>
    <a href="/">← Zurück</a>
    <div id="content">Lade...</div>
    <script>
        fetch('/api/v2/dashboard').then(r => r.json()).then(d => {
            const stats = d.leitner_stats;
            document.getElementById('content').innerHTML = `
                <div class="card">
                    <h2>Leitner Boxen</h2>
                    <p>Box 1 (Neu): ${stats.box_distribution.box_1_new}</p>
                    <p>Box 2-3 (Lernen): ${stats.box_distribution.box_2_learning + stats.box_distribution.box_3_learning}</p>
                    <p>Box 4 (Wiederholen): ${stats.box_distribution.box_4_review}</p>
                    <p>🏆 Box 5 (Gemeistert): ${stats.box_distribution.box_5_mastered}</p>
                    <p><strong>Heute fällig: ${stats.due_for_review}</strong></p>
                    <p>Mastery: ${stats.mastery_percent}%</p>
                </div>
                <div class="card">
                    <h2>💡 Empfehlungen</h2>
                    ${d.recommendations.map(r => `<div class="rec">${r}</div>`).join('')}
                </div>
            `;
        });
    </script>
</body></html>
    """)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

# ============ AI Learning Assistant (LernMate) Endpoints ============

from services.ai_assistant_simple import SimpleAIAssistant, AssistantConfig

# Initialize AI assistant
ai_assistant = SimpleAIAssistant(
    config=AssistantConfig(
        local_gpu_url="http://127.0.0.1:11434",
        i7_url="http://10.42.0.44:11434",  # Direct to i7 Ollama
    ),
    db=db
)

class QuestionRequest(BaseModel):
    question: str
    context: Optional[str] = None
    card_id: Optional[int] = None
    backend: str = "auto"

class ConceptRequest(BaseModel):
    concept: str
    difficulty: str = "einfach"

class QuizGenRequest(BaseModel):
    topic: str
    difficulty: int = 1

@app.post("/api/v2/lernmate/ask")
async def lernmate_ask(req: QuestionRequest):
    """Ask the AI learning assistant a question."""
    return ai_assistant.ask(
        question=req.question,
        context=req.context,
        card_id=req.card_id,
        backend=req.backend
    )

@app.post("/api/v2/lernmate/explain")
async def lernmate_explain(req: ConceptRequest):
    """Get a detailed explanation of a concept."""
    return ai_assistant.explain(req.concept, req.difficulty)

@app.post("/api/v2/lernmate/quiz/generate")
async def lernmate_generate_quiz(req: QuizGenRequest):
    """Generate a quiz question on a topic."""
    return ai_assistant.generate_quiz(req.topic, req.difficulty)

@app.get("/api/v2/lernmate/summarize/{video_id}")
async def lernmate_summarize(video_id: int, max_length: int = 200):
    """Summarize a video transcript."""
    return await ai_assistant.summarize_transcript(video_id, max_length)

@app.get("/api/v2/lernmate/models")
async def lernmate_models():
    """List available AI models and backends."""
    return {
        "models": ai_assistant.models,
        "backends": {
            "local_gpu": ai_assistant.config.local_gpu_url,
            "i7": ai_assistant.config.i7_url,
        },
        "status": "online"
    }

# ============ Enhanced Learning Features ============

@app.get("/api/v2/learning/recommendations")
async def get_recommendations(user_id: str = "default"):
    """Get personalized learning recommendations."""
    stats = await db.get_learning_stats(user_id)
    
    recommendations = []
    
    # Analyze weak areas
    cursor = await db.conn.execute("""
        SELECT v.theme, 
               COUNT(*) as total,
               SUM(CASE WHEN lc.leitner_box >= 3 THEN 1 ELSE 0 END) as mastered,
               AVG(lc.correct_streak) as avg_streak
        FROM learning_cards lc
        JOIN videos v ON lc.video_id = v.id
        GROUP BY v.theme
        HAVING total > 0
    """)
    
    for row in await cursor.fetchall():
        mastery_rate = row['mastered'] / row['total'] if row['total'] > 0 else 0
        if mastery_rate < 0.3:
            recommendations.append({
                "type": "weak_area",
                "theme": row['theme'],
                "priority": "high",
                "message": f"Thema '{row['theme']}' braucht mehr Übung ({int(mastery_rate*100)}% gemeistert)",
                "action": "review"
            })
        elif mastery_rate < 0.7:
            recommendations.append({
                "type": "practice",
                "theme": row['theme'],
                "priority": "medium",
                "message": f"Thema '{row['theme']}' weiter festigen ({int(mastery_rate*100)}% gemeistert)",
                "action": "practice"
            })
    
    # Due cards
    if stats.get("due_for_review", 0) > 0:
        recommendations.insert(0, {
            "type": "due_cards",
            "priority": "urgent",
            "message": f"{stats['due_for_review']} Karten sind heute fällig!",
            "action": "review_now"
        })
    
    return {
        "recommendations": recommendations[:5],
        "stats": stats
    }

@app.get("/api/v2/learning/analytics")
async def get_analytics(user_id: str = "default", days: int = 30):
    """Get detailed learning analytics."""
    cursor = await db.conn.execute("""
        SELECT 
            session_date,
            SUM(correct_count) as correct,
            SUM(incorrect_count) as incorrect,
            COUNT(DISTINCT card_id) as unique_cards
        FROM user_sessions
        WHERE session_date >= date('now', ? || ' days')
        GROUP BY session_date
        ORDER BY session_date
    """, (f"-{days}",))
    
    daily = [dict(r) for r in await cursor.fetchall()]
    
    # Calculate streaks
    total_correct = sum(d['correct'] for d in daily)
    total_incorrect = sum(d['incorrect'] for d in daily)
    accuracy = total_correct / (total_correct + total_incorrect) if (total_correct + total_incorrect) > 0 else 0
    
    return {
        "daily_stats": daily,
        "summary": {
            "total_correct": total_correct,
            "total_incorrect": total_incorrect,
            "accuracy": round(accuracy * 100, 1),
            "active_days": len(daily),
            "avg_per_day": round(total_correct / len(daily), 1) if daily else 0
        },
        "period_days": days
    }

@app.post("/api/v2/learning/batch-review")
async def batch_review(reviews: List[Dict]):
    """Submit multiple card reviews at once."""
    results = []
    for review in reviews:
        result = await db.review_card(
            review.get("card_id"),
            review.get("correct", False),
            review.get("user_id", "default")
        )
        results.append(result)
    return {"processed": len(results), "results": results}
