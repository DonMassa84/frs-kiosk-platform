#!/usr/bin/env python3
"""
FRS Archive & Kiosk Platform - FastAPI Backend

Provides REST API for:
- Video archive browsing and search
- Transcript full-text search
- Learning cards and progress tracking
- Vision analysis results
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.database import CourseDatabase

app = FastAPI(
    title="FRS Archive & Kiosk Platform",
    description="Unified platform for FRS broadcast archive and IHK learning kiosk",
    version="1.0.0"
)

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database instance
db = CourseDatabase()

# Static files (frontends)
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# Pydantic models
class CardProgress(BaseModel):
    correct: bool

class SearchResult(BaseModel):
    videos: List[Dict]
    transcripts: List[Dict]


# ============ FRS Archive Endpoints ============

@app.get("/api/frs/videos", response_model=List[Dict])
async def get_videos(
    lecturer: Optional[str] = None,
    theme: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """Get video archive with optional filtering."""
    return db.get_videos(lecturer=lecturer, theme=theme, limit=limit)


@app.get("/api/frs/search")
async def search_archive(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100)
):
    """Full-text search across video transcripts."""
    results = db.search_transcripts(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/frs/lecturers")
async def get_lecturers():
    """Get list of all lecturers."""
    c = db.conn.cursor()
    rows = c.execute("SELECT DISTINCT lecturer, COUNT(*) as count FROM videos GROUP BY lecturer ORDER BY count DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/frs/themes")
async def get_themes():
    """Get list of all themes."""
    c = db.conn.cursor()
    rows = c.execute("SELECT DISTINCT theme, COUNT(*) as count FROM videos GROUP BY theme ORDER BY count DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/frs/stats")
async def get_stats():
    """Get archive statistics."""
    c = db.conn.cursor()
    stats = {
        "total_videos": c.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
        "total_transcripts": c.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0],
        "total_words": c.execute("SELECT SUM(word_count) FROM transcripts").fetchone()[0] or 0,
        "vision_analyses": c.execute("SELECT COUNT(*) FROM vision_analysis").fetchone()[0],
        "lecturers": c.execute("SELECT COUNT(DISTINCT lecturer) FROM videos").fetchone()[0],
        "themes": c.execute("SELECT COUNT(DISTINCT theme) FROM videos").fetchone()[0],
    }
    return stats


@app.get("/api/frs/vision/{video_id}")
async def get_vision_analysis(video_id: int):
    """Get vision analysis results for a video."""
    c = db.conn.cursor()
    rows = c.execute("""
        SELECT * FROM vision_analysis WHERE video_id = ? ORDER BY timestamp_seconds
    """, (video_id,)).fetchall()
    return [dict(r) for r in rows]


# ============ Kiosk Endpoints ============

@app.get("/api/kiosk/cards")
async def get_cards(
    status: Optional[str] = Query(None, regex="^(new|learning|mastered|review)$"),
    limit: int = Query(20, le=100)
):
    """Get learning cards for kiosk, optionally filtered by status."""
    return db.get_learning_cards(status=status, limit=limit)


@app.post("/api/kiosk/cards/{card_id}/progress")
async def update_progress(card_id: int, progress: CardProgress):
    """Update learning progress for a card."""
    result = db.update_card_progress(card_id, progress.correct)
    return result


@app.get("/api/kiosk/stats")
async def get_kiosk_stats():
    """Get kiosk learning statistics."""
    c = db.conn.cursor()
    stats = {
        "total_cards": c.execute("SELECT COUNT(*) FROM learning_cards").fetchone()[0],
        "new": c.execute("SELECT COUNT(*) FROM learning_progress WHERE status='new'").fetchone()[0],
        "learning": c.execute("SELECT COUNT(*) FROM learning_progress WHERE status='learning'").fetchone()[0],
        "mastered": c.execute("SELECT COUNT(*) FROM learning_progress WHERE status='mastered'").fetchone()[0],
        "review": c.execute("SELECT COUNT(*) FROM learning_progress WHERE status='review'").fetchone()[0],
    }
    # Calculate mastery percentage
    total = stats["total_cards"]
    stats["mastery_percent"] = round(stats["mastered"] / total * 100, 1) if total > 0 else 0
    return stats


@app.get("/api/kiosk/quiz")
async def get_quiz(count: int = Query(10, le=50)):
    """Get random quiz cards."""
    c = db.conn.cursor()
    rows = c.execute("""
        SELECT lc.*, v.filename, v.theme 
        FROM learning_cards lc
        LEFT JOIN videos v ON lc.video_id = v.id
        ORDER BY RANDOM() LIMIT ?
    """, (count,)).fetchall()
    return [dict(r) for r in rows]


# ============ Frontend Routes ============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Platform home."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FRS Archive & Kiosk Platform</title>
        <style>
            body { font-family: system-ui, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            h1 { color: #2c3e50; }
            .card { background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 10px 0; }
            a { color: #3498db; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>🎓 FRS Archive & Kiosk Platform</h1>
        <div class="card">
            <h2>📚 FRS Archive</h2>
            <p>Browse and search the broadcast archive with full-text transcript search.</p>
            <a href="/frs">→ Open FRS Archive</a>
        </div>
        <div class="card">
            <h2>🖥️ Learning Kiosk</h2>
            <p>Interactive learning cards for IHK exam preparation.</p>
            <a href="/kiosk">→ Open Kiosk</a>
        </div>
        <div class="card">
            <h2>📊 API Documentation</h2>
            <a href="/docs">→ OpenAPI Docs</a> | 
            <a href="/redoc">→ ReDoc</a>
        </div>
    </body>
    </html>
    """


@app.get("/frs", response_class=HTMLResponse)
async def frs_archive():
    """FRS Archive frontend."""
    html_file = FRONTEND_DIR / "frs-archive" / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding='utf-8'))
    return HTMLResponse("<h1>FRS Archive - Frontend not found</h1>", status_code=404)


@app.get("/kiosk", response_class=HTMLResponse)
async def kiosk():
    """Kiosk frontend."""
    html_file = FRONTEND_DIR / "kiosk" / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding='utf-8'))
    return HTMLResponse("<h1>Kiosk - Frontend not found</h1>", status_code=404)


@app.on_event("shutdown")
def shutdown():
    db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ============ Erweiterte Features (generiert mit qwen2.5-coder:14b) ============

@app.get("/api/dashboard")
async def get_dashboard():
    """Dashboard: Lernfortschritt und Statistiken."""
    c = db.conn.cursor()
    
    # Lernfortschritt über Zeit (letzte 7 Tage)
    progress_over_time = c.execute("""
        SELECT DATE(updated_at) as date, 
               SUM(CASE WHEN status='mastered' THEN 1 ELSE 0 END) as mastered,
               COUNT(*) as total_reviewed
        FROM learning_progress 
        WHERE updated_at >= date('now', '-7 days')
        GROUP BY DATE(updated_at)
        ORDER BY date
    """).fetchall()
    
    # Themen-Verteilung
    theme_stats = c.execute("""
        SELECT v.theme, COUNT(DISTINCT lc.id) as card_count,
               SUM(CASE WHEN lp.status='mastered' THEN 1 ELSE 0 END) as mastered
        FROM learning_cards lc
        JOIN videos v ON lc.video_id = v.id
        LEFT JOIN learning_progress lp ON lc.id = lp.card_id
        GROUP BY v.theme
    """).fetchall()
    
    # Top-Lernende (nach gemeisterten Karten)
    top_learners = c.execute("""
        SELECT user_id, COUNT(*) as mastered_count
        FROM learning_progress 
        WHERE status='mastered'
        GROUP BY user_id 
        ORDER BY mastered_count DESC 
        LIMIT 5
    """).fetchall()
    
    return {
        "progress_over_time": [dict(r) for r in progress_over_time],
        "theme_stats": [dict(r) for r in theme_stats],
        "top_learners": [dict(r) for r in top_learners],
        "summary": {
            "total_cards": c.execute("SELECT COUNT(*) FROM learning_cards").fetchone()[0],
            "mastered_cards": c.execute("SELECT COUNT(*) FROM learning_progress WHERE status='mastered'").fetchone()[0],
            "active_users": c.execute("SELECT COUNT(DISTINCT user_id) FROM learning_progress WHERE updated_at >= date('now', '-1 day')").fetchone()[0]
        }
    }


@app.get("/api/export/cards")
async def export_cards(format: str = Query("json", regex="^(json|csv)$")):
    """Export Lernkarten als JSON oder CSV."""
    from fastapi.responses import Response
    import csv as csv_module
    import io
    
    c = db.conn.cursor()
    cards = c.execute("""
        SELECT lc.question, lc.answer, lc.tags, v.theme, v.lecturer, lc.difficulty
        FROM learning_cards lc
        LEFT JOIN videos v ON lc.video_id = v.id
    """).fetchall()
    
    if format == "csv":
        output = io.StringIO()
        writer = csv_module.writer(output)
        writer.writerow(["Frage", "Antwort", "Tags", "Thema", "Dozent", "Schwierigkeit"])
        for card in cards:
            writer.writerow([card['question'], card['answer'], card['tags'], 
                           card['theme'], card['lecturer'], card['difficulty']])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=lernkarten.csv"}
        )
    else:
        return [dict(card) for card in cards]


@app.get("/api/lecturers/compare")
async def compare_lecturers():
    """Dozenten-Vergleich: Anzahl Videos, Themen, durchschnittliche Länge."""
    c = db.conn.cursor()
    rows = c.execute("""
        SELECT 
            lecturer,
            COUNT(*) as video_count,
            COUNT(DISTINCT theme) as theme_count,
            AVG(duration_seconds)/60 as avg_duration_min,
            SUM(transcript_words) as total_words,
            COUNT(DISTINCT lc.id) as card_count
        FROM videos v
        LEFT JOIN learning_cards lc ON v.id = lc.video_id
        GROUP BY lecturer
        ORDER BY video_count DESC
    """).fetchall()
    return [dict(r) for r in rows]


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Dashboard frontend."""
    html_file = FRONTEND_DIR / "dashboard" / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding='utf-8'))
    return HTMLResponse("<h1>Dashboard - Frontend nicht gefunden</h1>", status_code=404)
