# Content Pipeline Design: מקורב לצלחת

**Date:** 2026-04-11  
**Status:** Approved — ready for implementation  
**Goal:** Turn ~30 audio recordings into a full editorial website with minimal manual work

---

## Problem

We have a working 3-page site (homepage, one article, about) deployed on Vercel. We need to scale from 1 article to ~30, using audio field recordings as source material. The recordings live on Google Drive because local disk space is limited.

## Solution: Script Pipeline

A single Python script (`generate.py`) that processes audio files from Google Drive, generates articles via Whisper + Claude APIs, and outputs ready-to-publish HTML pages.

---

## Pipeline Flow

```
Google Drive folder (audio files)
        │
        ▼
   Download one file to /tmp (~20-50MB)
        │
        ▼
   Convert WAV → MP3 (ffmpeg, 64kbps mono)
        │
        ▼
   Whisper API → transcript (JSON with timestamps)
        │
        ▼
   Claude API → structured article (JSON)
        │
        ▼
   HTML template injection → episodes/{slug}.html
        │
        ▼
   Delete temp audio file
        │
        ▼
   Next file... (repeat for all ~30)
        │
        ▼
   Regenerate index.html with all episode cards
        │
        ▼
   Output to drafts/ for batch review
```

### Disk usage
- Peak: ~50MB (one WAV + its MP3 conversion)
- Each file is deleted after processing before the next begins
- Final output: ~30 HTML files + images ≈ negligible

### Processing time
- Whisper API: ~30 seconds per episode
- Claude API: ~30 seconds per episode  
- Total: ~30-45 minutes for all 30 episodes

### Cost estimate
- Whisper: ~$0.10/episode × 30 = ~$3
- Claude: ~$0.15/episode × 30 = ~$4.50
- **Total: ~$8**

---

## Claude API Prompt Design

Each transcript is sent to Claude with a structured prompt that returns JSON:

### Input
- Raw transcript text
- Location name (extracted from filename or metadata)
- Episode number / date

### Output JSON schema
```json
{
  "slug": "ramle",
  "title": "שלוש תחנות בשוק רמלה",
  "deck": "חומוס של משפחה נוצרית, דוסה הודית...",
  "kicker": "סיור קולינרי",
  "location": "שוק רמלה",
  "date": "15.01.2026",
  "stations": [
    {
      "number": 1,
      "name": "חומוס סלים",
      "descriptor": "משפחה נוצרית · מ-2007",
      "color": "primary"
    }
  ],
  "body_paragraphs": [
    "כשרויטל אמרה לי ששוק רמלה הוא בטופ שלושה...",
    "..."
  ],
  "pull_quotes": [
    {
      "text": "עסק משפחתי, מכינים את האוכל בידיים שלנו...",
      "attribution": "מייקל, חומוס סלים",
      "after_paragraph": 3,
      "color": "primary"
    }
  ],
  "highlight_quotes": [
    {
      "text": "אצל הרמלאים והלודאים, זה תרבות הרי...",
      "attribution": "מייקל",
      "after_paragraph": 5
    }
  ],
  "youtube_id": null,
  "google_maps_searches": [
    "חומוס+סלים+רמלה",
    "מאמא+אינדיה+רמלה",
    "ממתקי+שהין+רמלה"
  ]
}
```

### Prompt guidelines for Claude
- Style: Narrative, first person — as if the host is walking the reader through
- Tone: Warm, curious, literary. Longform food journalism
- Quotes: Real quotes from the transcript, unpolished spoken Hebrew
- Length: 600-900 words
- Structure: Organized around "stations" / stops visited
- Each station gets a numbered header, at least one pull quote
- Identify speakers from context (vendors, guides, the host)

---

## HTML Template

The article template is derived from `episodes/ramle.html` — the existing working page. It has slots for:

| Slot | Source |
|------|--------|
| `{{title}}` | JSON `.title` |
| `{{deck}}` | JSON `.deck` |
| `{{kicker}}` | JSON `.kicker` |
| `{{location}}` | JSON `.location` |
| `{{date}}` | JSON `.date` |
| `{{stations}}` | Loop over JSON `.stations` |
| `{{body}}` | Interleave `.body_paragraphs` with `.pull_quotes` and `.highlight_quotes` |
| `{{youtube_embed}}` | Conditional — if `.youtube_id` exists |
| `{{map_svg}}` | Generated per-episode or reuse schematic |
| `{{map_listings}}` | From `.stations` + `.google_maps_searches` |

### Template engine
Simple Python string replacement or Jinja2. No framework needed.

### Photo handling
- Photos are NOT auto-generated — they're added manually per episode
- Template includes placeholder divs that render gracefully when no image exists
- Image slots: hero photo, one per station (optional), one full-width break

---

## Homepage Generation

After all episodes are generated, the script rebuilds `index.html`:

1. Scan `episodes/` folder for all `.html` files
2. Extract metadata from each (title, deck, location, date, slug) — stored in a `metadata.json` sidecar
3. Sort by date (newest first)
4. Generate episode cards grid
5. First card becomes the hero featured article
6. Write `index.html`

---

## YouTube Matching

The YouTube playlist contains video versions of the episodes. Matching strategy:

1. The script takes the YouTube playlist URL as input
2. Uses `yt-dlp --flat-playlist` to get all video titles + IDs
3. Fuzzy-matches video titles to episode titles (both contain the location name)
4. Stores the `youtube_id` in the episode metadata
5. Template embeds the video if a match is found

---

## Google Drive Integration

### Authentication
- Use Google Drive API via service account or OAuth (one-time setup)
- Or simpler: use `gdown` if files are shared via link
- Or simplest: use `rclone` which handles Drive auth well

### File discovery
- Script takes a Drive folder path/ID as input
- Lists all audio files (`.wav`, `.mp3`, `.m4a`)
- Downloads one at a time to `/tmp/mkorav/`

### Filename convention
Audio files should be named with the location for the script to extract metadata:
```
שוק רמלה.wav
יפו.wav
שוק נתניה.wav
שדה בנגב.wav
```

If filenames aren't clean, the script falls back to asking Claude to identify the location from the transcript.

---

## File Structure (after pipeline runs)

```
/
├── generate.py              ← the pipeline script
├── template.html             ← article page template
├── metadata.json             ← all episodes metadata
├── index.html                ← auto-generated homepage
├── about.html                ← static (already exists)
├── episodes/
│   ├── ramle.html            ← existing
│   ├── yafo.html             ← generated
│   ├── netanya.html          ← generated
│   └── ...
├── transcripts/
│   ├── ramle.json            ← raw Whisper output
│   ├── yafo.json
│   └── ...
├── articles/
│   ├── ramle.json            ← Claude structured output
│   ├── yafo.json
│   └── ...
├── images/
│   ├── hummus-salim.jpg      ← existing
│   └── ...                   ← add per episode manually
└── docs/
    └── plans/
        └── this file
```

---

## Batch Review Workflow

1. Run `python generate.py --drive-folder "מקורב לצלחת"` 
2. Script processes all 30 episodes → outputs to `episodes/`
3. Open `http://localhost:8080` to review all pages locally
4. Fix any issues (edit HTML directly or re-run individual episodes)
5. `git add . && git commit && git push` → Vercel auto-deploys

### Re-running a single episode
```bash
python generate.py --file "שוק נתניה.wav" --force
```

---

## Future Evolution (not for now)

When the show continues producing new episodes:

- **Phase 2:** Wrap `generate.py` in a GitHub Action. Drop audio to Drive → trigger webhook → auto-generate → create PR for review
- **Phase 3:** Add Spotify embed per episode (match by title, similar to YouTube matching)
- **Phase 4:** Newsletter integration — auto-generate email summary when new episode publishes

---

## Dependencies

| Tool | Purpose | Status |
|------|---------|--------|
| Python 3 | Script runtime | Installed |
| ffmpeg | Audio conversion | Installed |
| OpenAI API (Whisper) | Transcription | Key available |
| Anthropic API (Claude) | Article generation | Key needed |
| gdown / rclone | Google Drive download | To install |
| yt-dlp | YouTube playlist parsing | To install |
| Jinja2 | HTML templating | To install |

---

## Implementation order

1. Extract HTML template from `episodes/ramle.html`
2. Build the Claude prompt + JSON schema
3. Build `generate.py` — test with one local file first
4. Add Google Drive download
5. Add YouTube matching
6. Add homepage regeneration
7. Run full batch on all 30 episodes
8. Batch review + publish
