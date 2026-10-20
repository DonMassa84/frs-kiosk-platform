#!/usr/bin/env python3
"""
FRS Kiosk Platform Database V2 - Best Practices Implementation

Improvements based on Mistral AI recommendations:
- aiosqlite for async connection pooling
- FTS5 with bm25() ranking
- Leitner box system for spaced repetition (easier than FSRS, ready for migration)
- PRAGMA tuning for performance
- Batch operations with executemany
"""

import os
import aiosqlite
import json
import hashlib
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "frs-kiosk-platform" / "data" / "course_platform_v2.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

FRS_DATA_ROOT = Path(os.environ.get("FRS_DATA_ROOT", Path.home() / "Schreibtisch")).expanduser()
COURSE_DATA = Path(os.environ.get("FRS_COURSE_DATA", FRS_DATA_ROOT / "kursmaterial-pruefung")).expanduser()

# Leitner Box intervals (in days) - easy to implement, ready for FSRS migration
LEITNER_INTERVALS = [1, 3, 7, 14, 30]  # Box 1-5 intervals


class CourseDatabaseV2:
    """V2 Database with async support and best practices."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self._pool = None
    
    async def connect(self):
        """Async connection with PRAGMA tuning."""
        self.conn = await aiosqlite.connect(str(self.db_path))
        self.conn.row_factory = aiosqlite.Row
        
        # PRAGMA tuning for performance (Best Practice)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA temp_store=MEMORY")
        await self.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        
        await self._init_schema()
    
    async def _init_schema(self):
        """Initialize schema with V2 improvements."""
        c = self.conn
        
        # Videos table (same as V1)
        await c.execute("""CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            path TEXT NOT NULL,
            filename TEXT,
            date TEXT,
            lecturer TEXT,
            theme TEXT,
            duration_seconds REAL,
            file_size_bytes INTEGER,
            transcript_path TEXT,
            transcript_status TEXT,
            transcript_words INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Transcripts with FTS5 (Best Practice: unicode61 + content= for sync)
        await c.execute("""CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            path TEXT NOT NULL,
            content TEXT NOT NULL,
            word_count INTEGER,
            quality_score REAL,
            is_valid BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )""")
        
        # FTS5 with unicode61 tokenizer (Best Practice)
        await c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts 
            USING fts5(content, content=transcripts, content_rowid=id, tokenize='unicode61')""")
        
        # V2: Leitner Box System for Spaced Repetition (Best Practice: easy to implement)
        await c.execute("""CREATE TABLE IF NOT EXISTS learning_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            card_type TEXT,
            question TEXT,
            answer TEXT,
            hint TEXT,
            difficulty INTEGER DEFAULT 1,
            tags TEXT,
            source_timestamp REAL,
            -- Leitner system fields
            leitner_box INTEGER DEFAULT 1,  -- Box 1-5
            correct_streak INTEGER DEFAULT 0,
            incorrect_streak INTEGER DEFAULT 0,
            last_reviewed TIMESTAMP,
            next_review TIMESTAMP,
            total_reviews INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )""")
        
        # Simplified progress tracking (replaces separate table)
        await c.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            card_id INTEGER,
            session_date DATE DEFAULT CURRENT_DATE,
            correct_count INTEGER DEFAULT 0,
            incorrect_count INTEGER DEFAULT 0,
            FOREIGN KEY (card_id) REFERENCES learning_cards(id)
        )""")
        
        # Vision analysis (same as V1)
        await c.execute("""CREATE TABLE IF NOT EXISTS vision_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            frame_path TEXT,
            timestamp_seconds REAL,
            analysis_text TEXT,
            detected_keywords TEXT,
            model_used TEXT,
            gpu_bytes INTEGER,
            validation_status TEXT DEFAULT 'UNVERIFIED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )""")
        
        # Cache table for query results (Best Practice: async caching)
        await c.execute("""CREATE TABLE IF NOT EXISTS query_cache (
            cache_key TEXT PRIMARY KEY,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )""")
        
        # Indexes
        await c.execute("CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(date)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_videos_lecturer ON videos(lecturer)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_cards_box ON learning_cards(leitner_box)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_cards_next_review ON learning_cards(next_review)")
        
        await c.commit()
    
    async def search_transcripts(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Full-text search with bm25() ranking (Best Practice).
        """
        # Check cache first (Best Practice: caching)
        cache_key = f"search:{hashlib.md5(query.encode()).hexdigest()}:{limit}"
        cached = await self.conn.execute(
            "SELECT result FROM query_cache WHERE cache_key = ? AND expires_at > datetime('now')",
            (cache_key,)
        )
        cached = await cached.fetchone()
        if cached:
            return json.loads(cached['result'])
        
        # FTS5 query with bm25() ranking (Best Practice)
        cursor = await self.conn.execute("""
            SELECT t.id, t.video_id, v.filename, v.lecturer, v.theme,
                   snippet(transcripts_fts, 0, '[', ']', '...', 10) as snippet,
                   bm25(transcripts_fts) as rank
            FROM transcripts_fts fts
            JOIN transcripts t ON fts.rowid = t.id
            LEFT JOIN videos v ON t.video_id = v.id
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        results = [dict(row) for row in await cursor.fetchall()]
        
        # Cache result for 5 minutes (Best Practice)
        expires = datetime.now() + timedelta(minutes=5)
        await self.conn.execute("""
            INSERT OR REPLACE INTO query_cache (cache_key, result, expires_at)
            VALUES (?, ?, ?)
        """, (cache_key, json.dumps(results), expires))
        await self.conn.commit()
        
        return results
    
    async def get_cards_for_review(self, user_id: str = 'default', limit: int = 20) -> List[Dict]:
        """
        Get cards due for review using Leitner system (Best Practice).
        Cards in lower boxes and overdue cards are prioritized.
        """
        cursor = await self.conn.execute("""
            SELECT lc.*, v.filename, v.lecturer, v.theme
            FROM learning_cards lc
            LEFT JOIN videos v ON lc.video_id = v.id
            WHERE lc.next_review <= datetime('now') OR lc.next_review IS NULL
            ORDER BY 
                CASE lc.leitner_box 
                    WHEN 1 THEN 1  -- Review box 1 first
                    WHEN 2 THEN 2
                    WHEN 3 THEN 3
                    WHEN 4 THEN 4
                    ELSE 5
                END,
                lc.next_review ASC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in await cursor.fetchall()]
    
    async def review_card(self, card_id: int, correct: bool, user_id: str = 'default') -> Dict:
        """
        Leitner Box Spaced Repetition (Best Practice: easy to implement).
        
        Correct: Move to next box (max 5), reset streak
        Incorrect: Move back to box 1, reset streak
        """
        cursor = await self.conn.execute(
            "SELECT * FROM learning_cards WHERE id = ?", (card_id,)
        )
        card = await cursor.fetchone()
        
        if not card:
            return {"error": "Card not found"}
        
        current_box = card['leitner_box']
        
        if correct:
            # Move to next box (max 5)
            new_box = min(current_box + 1, 5)
            new_streak = card['correct_streak'] + 1
            incorrect_streak = 0
        else:
            # Move back to box 1
            new_box = 1
            new_streak = 0
            incorrect_streak = card['incorrect_streak'] + 1
        
        # Calculate next review date based on box (Leitner intervals)
        interval_days = LEITNER_INTERVALS[new_box - 1] if new_box <= 5 else 30
        next_review = datetime.now() + timedelta(days=interval_days)
        
        # Update card (Best Practice: batch with session log)
        await self.conn.execute("""
            UPDATE learning_cards 
            SET leitner_box = ?,
                correct_streak = ?,
                incorrect_streak = ?,
                last_reviewed = CURRENT_TIMESTAMP,
                next_review = ?,
                total_reviews = total_reviews + 1
            WHERE id = ?
        """, (new_box, new_streak, incorrect_streak, next_review, card_id))
        
        # Log session (for statistics)
        await self.conn.execute("""
            INSERT INTO user_sessions (user_id, card_id, correct_count, incorrect_count)
            VALUES (?, ?, ?, ?)
        """, (user_id, card_id, 1 if correct else 0, 0 if correct else 1))
        
        await self.conn.commit()
        
        # Calculate mastery level
        mastery = (new_box / 5) * 100
        
        return {
            "card_id": card_id,
            "correct": correct,
            "new_box": new_box,
            "next_review": next_review.isoformat(),
            "mastery_percent": round(mastery, 1),
            "status": "mastered" if new_box == 5 else "learning" if new_box > 1 else "review"
        }
    
    async def get_learning_stats(self, user_id: str = 'default') -> Dict:
        """Get learning statistics with Leitner box distribution."""
        cursor = await self.conn.execute("""
            SELECT 
                COUNT(*) as total_cards,
                SUM(CASE WHEN leitner_box = 1 THEN 1 ELSE 0 END) as box_1,
                SUM(CASE WHEN leitner_box = 2 THEN 1 ELSE 0 END) as box_2,
                SUM(CASE WHEN leitner_box = 3 THEN 1 ELSE 0 END) as box_3,
                SUM(CASE WHEN leitner_box = 4 THEN 1 ELSE 0 END) as box_4,
                SUM(CASE WHEN leitner_box = 5 THEN 1 ELSE 0 END) as box_5,
                SUM(CASE WHEN next_review <= datetime('now') THEN 1 ELSE 0 END) as due_now,
                AVG(correct_streak) as avg_streak
            FROM learning_cards
        """)
        
        row = await cursor.fetchone()
        total = row['total_cards']
        
        return {
            "total_cards": total,
            "box_distribution": {
                "box_1_new": row['box_1'],
                "box_2_learning": row['box_2'],
                "box_3_learning": row['box_3'],
                "box_4_review": row['box_4'],
                "box_5_mastered": row['box_5']
            },
            "due_for_review": row['due_now'],
            "mastery_percent": round((row['box_5'] / total * 100), 1) if total > 0 else 0,
            "average_streak": round(row['avg_streak'] or 0, 1)
        }
    
    async def batch_import_videos(self, videos: List[Dict]):
        """Batch import with executemany (Best Practice: batch writes)."""
        await self.conn.executemany("""
            INSERT OR REPLACE INTO videos 
            (video_id, path, filename, date, lecturer, theme, file_size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            (v['video_id'], v['path'], v['filename'], v.get('date'),
             v.get('lecturer'), v.get('theme'), v.get('file_size_bytes', 0))
            for v in videos
        ])
        await self.conn.commit()
    
    async def close(self):
        if self.conn:
            await self.conn.close()


async def init_v2_database():
    """Initialize V2 database with course data."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    logging.basicConfig(level=logging.INFO)
    
    db = CourseDatabaseV2()
    await db.connect()
    
    # Import from V1 or re-import from source
    logger.info("V2 Database initialized with best practices")
    
    # Get stats
    stats = await db.get_learning_stats()
    logger.info(f"Stats: {stats}")
    
    await db.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_v2_database())
