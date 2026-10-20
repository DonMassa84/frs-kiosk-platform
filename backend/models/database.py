#!/usr/bin/env python3
"""
Unified Course Database for FRS Archive & Kiosk Platform
"""

import os
import sqlite3
import json
import hashlib
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "frs-kiosk-platform" / "data" / "course_platform.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Local data roots are configurable so the public source carries no user name.
# Defaults reproduce the original layout on the author's machine.
FRS_DATA_ROOT = Path(os.environ.get("FRS_DATA_ROOT", Path.home() / "Schreibtisch")).expanduser()
COURSE_DATA = Path(os.environ.get("FRS_COURSE_DATA", FRS_DATA_ROOT / "kursmaterial-pruefung")).expanduser()
VIDEO_INVENTORY = Path(os.environ.get("FRS_VIDEO_INVENTORY",
                                     Path.home() / "ihk-video-inventur" / "ihk-video-intelligence")).expanduser()


class CourseDatabase:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
    
    def _init_schema(self):
        c = self.conn.cursor()
        
        c.execute("""CREATE TABLE IF NOT EXISTS videos (
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
        
        c.execute("""CREATE TABLE IF NOT EXISTS transcripts (
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
        
        c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts 
            USING fts5(content, content=transcripts, content_rowid=id, tokenize='unicode61')""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS vision_analysis (
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
        
        c.execute("""CREATE TABLE IF NOT EXISTS learning_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            card_type TEXT,
            question TEXT,
            answer TEXT,
            hint TEXT,
            difficulty INTEGER DEFAULT 1,
            tags TEXT,
            source_timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER,
            user_id TEXT DEFAULT 'default',
            status TEXT DEFAULT 'new',
            correct_count INTEGER DEFAULT 0,
            incorrect_count INTEGER DEFAULT 0,
            last_reviewed TIMESTAMP,
            next_review TIMESTAMP,
            ease_factor REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (card_id) REFERENCES learning_cards(id)
        )""")
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_videos_lecturer ON videos(lecturer)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cards_type ON learning_cards(card_type)")
        
        self.conn.commit()
    
    def import_course_data(self):
        logger.info("Importing course data...")
        self._import_videos()
        self._import_transcripts()
        self._import_vision_results()
        self._generate_learning_cards()
        self._print_stats()
    
    def _extract_lecturer(self, filename: str) -> str:
        lecturers = {
            'specht': 'Frau Specht', 'dieterich': 'Dieterich',
            'vordermeier': 'Vordermeier', 'jehlitschke': 'Jehlitschke',
            'schmidt': 'Schmidt-Ursula', 'ulrich': 'Ulrich',
            'wellinger': 'Wellinger', 'entewickler': 'Entewickler',
            'friedrich': 'Friedrich', 'crnjac': 'Crnjac', 'gmt': 'GMT'
        }
        fn = filename.lower()
        for key, name in lecturers.items():
            if key in fn:
                return name
        return 'Unbekannt'
    
    def _extract_theme(self, filename: str) -> str:
        fn = filename.lower()
        if 'projektmanagement' in fn or 'projekt' in fn:
            return 'Projektmanagement'
        if 'it-bezogen' in fn or 'it-projekt' in fn:
            return 'IT-Projektmanagement'
        if 'datenschutz' in fn:
            return 'Datenschutz'
        if 'vwl' in fn or 'bwl' in fn or 'volks' in fn:
            return 'VWL/BWL'
        if 'mitarbeiter' in fn:
            return 'Mitarbeiterführung'
        if 'zoom' in fn or 'ihk' in fn:
            return 'IHK/Zoom'
        return 'Sonstiges'
    
    def _extract_keywords(self, text: str) -> List[str]:
        keywords = []
        pm_terms = ['Projekt', 'Meilenstein', 'Risiko', 'Ressource', 'Stakeholder',
                    'Budget', 'Zeitplan', 'Qualität', 'Scope', 'Agile', 'Scrum',
                    'Kanban', 'Gantt', 'PSP', 'Nutzwertanalyse', 'Arbeitsrecht']
        for term in pm_terms:
            if term.lower() in text.lower():
                keywords.append(term)
        return keywords[:10]
    
    def _import_videos(self):
        c = self.conn.cursor()
        inventory_file = COURSE_DATA / "videos.csv"
        if not inventory_file.exists():
            logger.warning(f"Not found: {inventory_file}")
            return
        
        count = 0
        with open(inventory_file, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                video_path = row['video']
                filename = Path(video_path).name
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
                
                video_id = hashlib.md5(video_path.encode()).hexdigest()[:12]
                
                c.execute("""INSERT OR REPLACE INTO videos 
                    (video_id, path, filename, date, lecturer, theme, file_size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    video_id, video_path, filename,
                    date_match.group(1) if date_match else None,
                    self._extract_lecturer(filename),
                    self._extract_theme(filename),
                    int(row.get('size_bytes', 0))
                ))
                count += 1
        
        self.conn.commit()
        logger.info(f"Imported {count} videos")
    
    def _import_transcripts(self):
        c = self.conn.cursor()
        fts_db = COURSE_DATA / "kursmaterial-kandidaten.sqlite3"
        if not fts_db.exists():
            logger.warning(f"Not found: {fts_db}")
            return
        
        fts_conn = sqlite3.connect(str(fts_db))
        fts_conn.row_factory = sqlite3.Row
        
        count = 0
        for row in fts_conn.execute("SELECT rowid, sha256, paths, videos, content FROM sources"):
            videos = json.loads(row['videos']) if row['videos'] else []
            video_id = None
            if videos:
                c.execute("SELECT id FROM videos WHERE path = ?", (videos[0],))
                v = c.fetchone()
                video_id = v['id'] if v else None
            
            content = row['content']
            word_count = len(content.split())
            quality = min(1.0, word_count / 10000)
            
            c.execute("""INSERT INTO transcripts (video_id, path, content, word_count, quality_score)
                VALUES (?, ?, ?, ?, ?)""", (
                video_id,
                json.loads(row['paths'])[0] if row['paths'] else '',
                content, word_count, quality
            ))
            
            tid = c.lastrowid
            c.execute("INSERT INTO transcripts_fts(rowid, content) VALUES (?, ?)", (tid, content))
            count += 1
        
        self.conn.commit()
        fts_conn.close()
        logger.info(f"Imported {count} transcripts")
    
    def _import_vision_results(self):
        c = self.conn.cursor()
        vision_dir = COURSE_DATA / "vision-ergebnisse" / "lokale-gpu"
        if not vision_dir.exists():
            return
        
        count = 0
        for result_dir in vision_dir.iterdir():
            if not result_dir.is_dir():
                continue
            rf = result_dir / "results.json"
            if not rf.exists():
                continue
            
            data = json.loads(rf.read_text(encoding='utf-8'))
            records = data.get('records', [])
            if not records:
                continue
            
            video_path = records[0].get('video')
            c.execute("SELECT id FROM videos WHERE path = ?", (video_path,))
            v = c.fetchone()
            video_id = v['id'] if v else None
            
            for rec in records:
                if rec.get('status') != 'ok':
                    continue
                text = rec.get('text', '')
                c.execute("""INSERT INTO vision_analysis 
                    (video_id, frame_path, timestamp_seconds, analysis_text, detected_keywords, model_used, gpu_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    video_id, rec.get('frame'), rec.get('time_seconds'),
                    text, json.dumps(self._extract_keywords(text)),
                    data.get('model', 'llava:7b'), rec.get('reported_gpu_bytes', 0)
                ))
                count += 1
        
        self.conn.commit()
        logger.info(f"Imported {count} vision results")
    
    def _generate_learning_cards(self):
        c = self.conn.cursor()
        count = 0
        
        for row in c.execute("""SELECT t.id, t.video_id, t.content, v.theme 
            FROM transcripts t JOIN videos v ON t.video_id = v.id 
            WHERE t.is_valid = 1 AND t.word_count > 500""").fetchall():
            
            content = row['content']
            theme = row['theme'] or 'Allgemein'
            sentences = re.split(r'[.!?]+', content)
            
            cards = 0
            for sent in sentences[:100]:
                sent = sent.strip()
                if len(sent) < 30 or len(sent) > 400:
                    continue
                if cards >= 3:
                    break
                
                # Create flashcard from sentence
                words = sent.split()
                if len(words) < 5:
                    continue
                
                # Question: first part, Answer: full sentence
                split_point = len(words) // 2
                question = ' '.join(words[:split_point]) + '...?'
                answer = sent
                
                c.execute("""INSERT INTO learning_cards 
                    (video_id, card_type, question, answer, tags, difficulty)
                    VALUES (?, 'flashcard', ?, ?, ?, 1)""", (
                    row['video_id'], question, answer, theme
                ))
                
                # Initialize progress
                card_id = c.lastrowid
                c.execute("""INSERT INTO learning_progress (card_id, status) VALUES (?, 'new')""", (card_id,))
                
                cards += 1
                count += 1
        
        self.conn.commit()
        logger.info(f"Generated {count} learning cards")
    
    def _print_stats(self):
        c = self.conn.cursor()
        stats = {}
        for table in ['videos', 'transcripts', 'vision_analysis', 'learning_cards', 'learning_progress']:
            stats[table] = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.info(f"Database stats: {stats}")
    
    def search_transcripts(self, query: str, limit: int = 10) -> List[Dict]:
        c = self.conn.cursor()
        results = c.execute("""
            SELECT t.id, t.video_id, v.filename, v.lecturer, v.theme, 
                   snippet(transcripts_fts, 0, '[', ']', '...', 10) as snippet
            FROM transcripts_fts fts
            JOIN transcripts t ON fts.rowid = t.id
            LEFT JOIN videos v ON t.video_id = v.id
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        return [dict(r) for r in results]
    
    def get_videos(self, lecturer: str = None, theme: str = None, limit: int = 50) -> List[Dict]:
        c = self.conn.cursor()
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
        
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    
    def get_learning_cards(self, status: str = None, limit: int = 20) -> List[Dict]:
        c = self.conn.cursor()
        sql = """SELECT lc.*, v.filename, v.lecturer, v.theme, lp.status as progress_status
            FROM learning_cards lc
            LEFT JOIN videos v ON lc.video_id = v.id
            LEFT JOIN learning_progress lp ON lc.id = lp.card_id
            WHERE 1=1"""
        params = []
        if status:
            sql += " AND lp.status = ?"
            params.append(status)
        sql += " ORDER BY lc.created_at DESC LIMIT ?"
        params.append(limit)
        
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    
    def update_card_progress(self, card_id: int, correct: bool):
        c = self.conn.cursor()
        c.execute("SELECT id, correct_count, incorrect_count, ease_factor, interval_days FROM learning_progress WHERE card_id = ?", (card_id,))
        prog = c.fetchone()
        
        if not prog:
            c.execute("INSERT INTO learning_progress (card_id) VALUES (?)", (card_id,))
            prog = c.execute("SELECT * FROM learning_progress WHERE card_id = ?", (card_id,)).fetchone()
        
        correct_count = prog['correct_count'] + (1 if correct else 0)
        incorrect_count = prog['incorrect_count'] + (0 if correct else 1)
        
        # Simple spaced repetition logic
        if correct:
            new_status = 'mastered' if correct_count >= 3 else 'learning'
            interval = prog['interval_days'] * 2
            ease = prog['ease_factor'] + 0.1
        else:
            new_status = 'review'
            interval = 1
            ease = max(1.3, prog['ease_factor'] - 0.2)
        
        from datetime import timedelta
        next_review = datetime.now() + timedelta(days=interval)
        
        c.execute("""UPDATE learning_progress 
            SET status = ?, correct_count = ?, incorrect_count = ?, 
                last_reviewed = CURRENT_TIMESTAMP, next_review = ?,
                ease_factor = ?, interval_days = ?, updated_at = CURRENT_TIMESTAMP
            WHERE card_id = ?""", (
            new_status, correct_count, incorrect_count, next_review,
            ease, interval, card_id
        ))
        
        self.conn.commit()
        return {'status': new_status, 'correct': correct_count, 'incorrect': incorrect_count}
    
    def close(self):
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = CourseDatabase()
    db.import_course_data()
    db.close()
