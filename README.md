# FRS Archive & Kiosk Platform

Unified platform for the FRS (Freies Radio Stuttgart) broadcast archive and IHK learning kiosk, integrating all processed course data.

## Features

### 📻 FRS Archive
- Browse 36 course videos by lecturer, theme, date
- Full-text search across all transcripts (FTS5)
- Vision analysis results from LLaVA (image descriptions)
- Statistics and filtering

### 🎓 Learning Kiosk
- Interactive flashcards generated from transcripts
- Spaced repetition learning algorithm
- Progress tracking (new/learning/mastered/review)
- Quiz mode with random cards
- Mastery percentage tracking

### 🔌 Backend API
- FastAPI REST API
- SQLite database with FTS5 full-text search
- Unified data model for videos, transcripts, vision analysis, learning cards

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database with course data
python backend/models/database.py

# Start the server
python backend/api/main.py
```

Then open:
- **Platform Home:** http://localhost:8000
- **FRS Archive:** http://localhost:8000/frs
- **Learning Kiosk:** http://localhost:8000/kiosk
- **API Docs:** http://localhost:8000/docs

## Data Sources

Integrates processed data from:
- `/home/shadowmaker/Schreibtisch/kursmaterial-pruefung/` - Processed course materials
- `/home/shadowmaker/ihk-video-inventur/` - Video inventory
- LLaVA vision analysis results (GPU)
- Audio transcriptions (Whisper CPU)

## Architecture

```
frs-kiosk-platform/
├── backend/
│   ├── api/main.py          # FastAPI REST API
│   ├── models/database.py   # SQLite database layer
│   └── services/            # Business logic services
├── frontend/
│   ├── frs-archive/         # FRS Archive web interface
│   └── kiosk/               # Learning kiosk interface
├── shared/                  # Shared utilities
└── data/                    # SQLite database
```

## i7 Deployment

See `deploy-i7.sh` for deployment to the i7 server.

## API Endpoints

### FRS Archive
- `GET /api/frs/videos` - List videos (filter by lecturer, theme)
- `GET /api/frs/search?q=...` - Full-text transcript search
- `GET /api/frs/lecturers` - List all lecturers
- `GET /api/frs/themes` - List all themes
- `GET /api/frs/stats` - Archive statistics
- `GET /api/frs/vision/{id}` - Vision analysis for video

### Kiosk
- `GET /api/kiosk/cards` - Get learning cards (filter by status)
- `POST /api/kiosk/cards/{id}/progress` - Update card progress
- `GET /api/kiosk/stats` - Learning statistics
- `GET /api/kiosk/quiz` - Get random quiz cards
