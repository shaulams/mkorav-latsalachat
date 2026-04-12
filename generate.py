#!/usr/bin/env python3
"""Content pipeline for מקורב לצלחת website."""

import argparse
import glob as globmod
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Use dotenv-style manual loading (no extra dependency)
def load_env():
    """Load .env file if it exists."""
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())

# Paths
BASE_DIR = Path(__file__).parent
TRANSCRIPTS_DIR = BASE_DIR / 'transcripts'
ARTICLES_DIR = BASE_DIR / 'articles'
EPISODES_DIR = BASE_DIR / 'episodes'
TEMPLATE_PATH = BASE_DIR / 'template.html'
TEMPLATE_HOMEPAGE_PATH = BASE_DIR / 'template_homepage.html'
IMAGES_DIR = BASE_DIR / 'images'

# Google Drive settings
DRIVE_FOLDER_ID = "1EuCBvCVC-QQXjUN_tma2B7m2Z10GOH6N"
DRIVE_REMOTE = "gdrive2"
TEMP_DIR = Path(tempfile.gettempdir()) / "mkorav"

def list_drive_episodes() -> list[dict]:
    """Use rclone to list all audio files in the Drive folder.

    Parses rclone ls output, filters to Final Cut/Mix/Final files,
    excludes teasers, handles duplicates, and checks special subfolders.

    Returns list of dicts with keys: name, filename, size, subfolder.
    """
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # List root folder
    result = subprocess.run(
        ['rclone', 'ls', f'{DRIVE_REMOTE}:', '--drive-root-folder-id', DRIVE_FOLDER_ID, '--max-depth', '1'],
        capture_output=True, text=True, check=True
    )
    root_files = _parse_rclone_ls(result.stdout, subfolder=None)

    # List subfolders (look for ספיישל directories)
    result_dirs = subprocess.run(
        ['rclone', 'lsd', f'{DRIVE_REMOTE}:', '--drive-root-folder-id', DRIVE_FOLDER_ID, '--max-depth', '1'],
        capture_output=True, text=True, check=True
    )
    subfolder_files = []
    for line in result_dirs.stdout.strip().splitlines():
        # lsd output: "          -1 2024-01-01 00:00:00        -1 ספיישל מצפה רמון"
        parts = line.strip().split()
        if len(parts) >= 5:
            folder_name = ' '.join(parts[4:])
        else:
            folder_name = line.strip().rsplit(None, 1)[-1] if line.strip() else ''
        if not folder_name:
            continue
        if 'ספיישל' in folder_name or 'special' in folder_name.lower():
            sub_result = subprocess.run(
                ['rclone', 'ls', f'{DRIVE_REMOTE}:{folder_name}/', '--drive-root-folder-id', DRIVE_FOLDER_ID, '--max-depth', '1'],
                capture_output=True, text=True, check=True
            )
            subfolder_files.extend(_parse_rclone_ls(sub_result.stdout, subfolder=folder_name))

    all_files = root_files + subfolder_files
    return _deduplicate_episodes(all_files)


def _parse_rclone_ls(output: str, subfolder: str | None) -> list[dict]:
    """Parse rclone ls output into episode dicts."""
    episodes = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: "228112816 Afula - Final Cut.wav"
        match = re.match(r'(\d+)\s+(.+)', line)
        if not match:
            continue
        size = int(match.group(1))
        filename = match.group(2)

        # Only audio files
        if not any(filename.lower().endswith(ext) for ext in ('.wav', '.mp3', '.m4a', '.flac', '.aac')):
            continue

        # Exclude teasers
        if 'teaser' in filename.lower() or 'טיזר' in filename:
            continue

        # For root files: filter to Final Cut / Final Mix / Final / special MP3s
        if subfolder is None:
            is_final = bool(re.search(r'final\s*(cut|mix|2)?', filename, re.IGNORECASE))
            is_special_mp3 = filename.lower().endswith('.mp3')  # e.g. "011124 שוק נתניה.mp3"
            if not is_final and not is_special_mp3:
                continue

        name = extract_episode_name(filename) if subfolder is None else extract_episode_name(subfolder)
        episodes.append({
            'name': name,
            'filename': filename,
            'size': size,
            'subfolder': subfolder,
        })
    return episodes


def _deduplicate_episodes(episodes: list[dict]) -> list[dict]:
    """Handle duplicates: prefer 'Final Cut' > 'Final 2' > 'Final Mix' > 'Final'."""
    by_name: dict[str, list[dict]] = {}
    for ep in episodes:
        by_name.setdefault(ep['name'], []).append(ep)

    result = []
    for name, eps in by_name.items():
        if len(eps) == 1:
            result.append(eps[0])
            continue
        # Score each candidate
        def _score(ep):
            fn = ep['filename'].lower()
            if 'final cut' in fn:
                return 4
            if 'final 2' in fn or 'final2' in fn:
                return 3
            if 'final mix' in fn:
                return 2
            if 'final' in fn:
                return 1
            return 0
        eps.sort(key=_score, reverse=True)
        result.append(eps[0])
    return result


def download_episode(episode: dict) -> str:
    """Download a single episode audio file from Drive to TEMP_DIR.

    Returns local path to downloaded file.
    """
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if episode['subfolder']:
        src = f"{DRIVE_REMOTE}:{episode['subfolder']}/{episode['filename']}"
    else:
        src = f"{DRIVE_REMOTE}:{episode['filename']}"
    subprocess.run(
        ['rclone', 'copy', src, str(TEMP_DIR), '--drive-root-folder-id', DRIVE_FOLDER_ID],
        capture_output=True, text=True, check=True
    )
    return str(TEMP_DIR / episode['filename'])


def extract_episode_name(filename: str) -> str:
    """Extract clean episode name from filename.

    'Afula - Final Cut.wav' -> 'Afula'
    'Bat Galim - Final Cut.wav' -> 'Bat Galim'
    '011124 שוק נתניה.mp3' -> 'שוק נתניה'
    'ספיישל מצפה רמון' (subfolder name) -> 'מצפה רמון'
    """
    name = filename

    # Handle subfolder names like "ספיישל מצפה רמון"
    if 'ספיישל' in name and '.' not in name:
        name = re.sub(r'ספיישל\s*', '', name).strip()
        return name

    # Remove file extension
    name = re.sub(r'\.(wav|mp3|m4a|flac|aac)$', '', name, flags=re.IGNORECASE)

    # Remove " - Final Cut", " - Final Mix", " - Final 2", " - Final" suffix
    name = re.sub(r'\s*-\s*[Ff]inal\s*([Cc]ut|[Mm]ix|2)?\s*$', '', name)

    # Handle date-prefixed Hebrew names: "011124 שוק נתניה" -> "שוק נתניה"
    name = re.sub(r'^\d{6}\s+', '', name)

    # Handle "מתוקן" (corrected) suffix
    name = re.sub(r'\s+מתוקן\s*$', '', name)

    return name.strip()


def cleanup_temp(path: str):
    """Delete a temp file."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def slugify(name: str) -> str:
    """Convert episode name to URL slug.
    'שוק רמלה' → 'ramle'
    'Gay Friendly Jerusalem' → 'gay-friendly-jerusalem'
    """
    # For Hebrew names, transliterate manually would be complex.
    # Use a simple approach: lowercase, replace spaces with hyphens, strip non-alphanum
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')
    return slug

def convert_to_mp3(input_path: str) -> str:
    """Convert audio to MP3 48kbps mono using ffmpeg. Returns MP3 path.
    Re-encodes even existing MP3s if they're over 24MB (Whisper limit is 25MB)."""
    MAX_SIZE = 24 * 1024 * 1024  # 24MB to stay safely under 25MB limit

    # If already MP3 and small enough, use as-is
    if input_path.endswith('.mp3') and os.path.getsize(input_path) <= MAX_SIZE:
        return input_path

    # Generate output path (add _small suffix if input is already mp3)
    if input_path.endswith('.mp3'):
        mp3_path = input_path.rsplit('.', 1)[0] + '_small.mp3'
    else:
        mp3_path = input_path.rsplit('.', 1)[0] + '.mp3'

    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-codec:a', 'libmp3lame', '-b:a', '48k', '-ac', '1',
        mp3_path, '-y'
    ], capture_output=True, check=True)
    return mp3_path

def transcribe(mp3_path: str) -> dict:
    """Send to OpenAI Whisper API, return verbose JSON."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    with open(mp3_path, 'rb') as f:
        result = client.audio.transcriptions.create(
            model='whisper-1',
            file=f,
            language='he',
            response_format='verbose_json',
            timestamp_granularities=['segment']
        )
    return result.model_dump()

def save_transcript(transcript: dict, slug: str) -> Path:
    """Save transcript to transcripts/{slug}.json."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPTS_DIR / f'{slug}.json'
    path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding='utf-8')
    return path

def load_article(slug: str) -> dict:
    """Load article JSON from articles/{slug}.json."""
    path = ARTICLES_DIR / f'{slug}.json'
    if not path.exists():
        raise FileNotFoundError(f'Article not found: {path}')
    return json.loads(path.read_text(encoding='utf-8'))

def render_body_html(article: dict) -> str:
    """Render article body: interleave paragraphs with pull quotes and highlight quotes."""
    # Build list of content blocks in order
    paragraphs = article.get('body_paragraphs', [])
    pull_quotes = sorted(article.get('pull_quotes', []), key=lambda q: q.get('after_paragraph', 0))
    highlight_quotes = sorted(article.get('highlight_quotes', []), key=lambda q: q.get('after_paragraph', 0))

    # Merge quotes into a position map
    inserts = {}  # paragraph_index → list of HTML strings to insert after

    for q in pull_quotes:
        pos = q.get('after_paragraph', len(paragraphs))
        color = q.get('color', 'primary')
        html = f'''
    <blockquote class="my-16 p-10 bg-surface-container-low border-r-8 border-{color} relative overflow-hidden">
      <p class="font-body text-2xl md:text-3xl italic leading-snug text-{color} relative z-10">
        "{q['text']}"
      </p>
      <span class="block mt-4 font-label text-sm text-on-surface-variant">— {q['attribution']}</span>
      <span class="material-symbols-outlined absolute -bottom-4 -left-4 text-9xl opacity-5 text-on-surface-variant">format_quote</span>
    </blockquote>'''
        inserts.setdefault(pos, []).append(html)

    for q in highlight_quotes:
        pos = q.get('after_paragraph', len(paragraphs))
        html = f'''
    <div class="py-12 text-center">
      <div class="w-12 h-1 bg-tertiary mx-auto mb-6"></div>
      <h4 class="font-headline text-2xl font-bold italic text-on-surface-variant px-8">
        "{q['text']}"
      </h4>
      <span class="block mt-4 font-label text-sm text-primary">— {q['attribution']}</span>
      <div class="w-12 h-1 bg-tertiary mx-auto mt-6"></div>
    </div>'''
        inserts.setdefault(pos, []).append(html)

    # Build HTML
    html_parts = []

    # Add station headers and paragraphs
    stations = article.get('stations', [])
    station_positions = {s.get('before_paragraph', 0): s for s in stations if 'before_paragraph' in s}

    for i, para in enumerate(paragraphs):
        # Check if a station header goes before this paragraph
        if i in station_positions:
            s = station_positions[i]
            colors = {'primary': 'primary', 'tertiary': 'tertiary', 'secondary': 'secondary'}
            color = colors.get(s.get('color', 'primary'), 'primary')
            html_parts.append(f'''
    <div class="flex items-start gap-6 mb-8 group mt-16">
      <div class="station-number bg-{color} text-on-{color}">{s['number']}</div>
      <div>
        <h3 class="font-headline font-bold text-2xl mb-1 group-hover:text-{color} transition-colors">{s['name']}</h3>
        <p class="font-label text-on-surface-variant">{s.get('descriptor', '')}</p>
      </div>
    </div>''')

        # Add paragraph
        html_parts.append(f'''
    <p class="font-body text-xl leading-[1.85] mb-12">
      {para}
    </p>''')

        # Add any quotes that come after this paragraph
        if i + 1 in inserts:
            html_parts.extend(inserts[i + 1])

    # Add any trailing inserts
    for pos in sorted(inserts.keys()):
        if pos > len(paragraphs):
            html_parts.extend(inserts[pos])

    return '\n'.join(html_parts)

def render_map_listings_html(article: dict) -> str:
    """Render station listings with Google Maps links."""
    stations = article.get('stations', [])
    searches = article.get('google_maps_searches', [])
    colors = ['primary', 'tertiary', 'secondary', 'primary', 'tertiary', 'secondary']

    parts = []
    for i, station in enumerate(stations):
        color = colors[i % len(colors)]
        search_query = searches[i] if i < len(searches) else station['name'].replace(' ', '+')
        maps_url = f'https://www.google.com/maps/search/{search_query}'

        parts.append(f'''
        <a href="{maps_url}" target="_blank" rel="noopener" class="flex gap-4 group">
          <span class="font-headline font-bold text-{color}">{str(i+1).zfill(2)}</span>
          <div>
            <h5 class="font-headline font-bold text-lg group-hover:text-primary-fixed transition-colors">{station['name']}</h5>
            <p class="text-sm text-surface-variant opacity-70">{station.get('descriptor', '')}</p>
            <span class="font-label text-xs text-primary-fixed opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 mt-1">
              <span class="material-symbols-outlined text-sm">pin_drop</span> פתח במפות
            </span>
          </div>
        </a>''')

    return '\n'.join(parts)

def render_episode_page(article: dict) -> str:
    """Render full episode HTML page using Jinja2 template."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(BASE_DIR)))
    template = env.get_template('template.html')

    body_html = render_body_html(article)
    map_listings_html = render_map_listings_html(article)

    return template.render(
        title=article.get('title', ''),
        deck=article.get('deck', ''),
        kicker=article.get('kicker', 'סיור קולינרי'),
        location=article.get('location', ''),
        date=article.get('date', ''),
        slug=article.get('slug', ''),
        body_html=body_html,
        youtube_id=article.get('youtube_id'),
        map_listings_html=map_listings_html,
        hero_image=article.get('hero_image'),
    )

def save_episode_page(html: str, slug: str) -> Path:
    """Write episode HTML to episodes/{slug}.html."""
    EPISODES_DIR.mkdir(exist_ok=True)
    path = EPISODES_DIR / f'{slug}.html'
    path.write_text(html, encoding='utf-8')
    return path

def _find_card_image(slug: str) -> str | None:
    """Find the first image in images/ matching the slug. Returns root-relative path or None."""
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        matches = sorted(IMAGES_DIR.glob(f'*{slug}*.{ext}'))
        if matches:
            return f'images/{matches[0].name}'
        # Also try exact slug prefix
        matches = sorted(IMAGES_DIR.glob(f'{slug}*.{ext}'))
        if matches:
            return f'images/{matches[0].name}'
    # Fallback: check all images in the directory for any containing the slug
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        for img in sorted(IMAGES_DIR.glob(f'*.{ext}')):
            if slug in img.stem.lower():
                return f'images/{img.name}'
    return None


def collect_all_metadata() -> list[dict]:
    """Scan articles/*.json, collect metadata for all episodes.

    Sort by date (newest first, parse DD.MM.YYYY format).
    Returns list of dicts with: slug, title, deck, location, date, hero_image, kicker, card_image.
    """
    ARTICLES_DIR.mkdir(exist_ok=True)
    episodes = []
    for article_file in sorted(ARTICLES_DIR.glob('*.json')):
        data = json.loads(article_file.read_text(encoding='utf-8'))
        slug = data.get('slug', article_file.stem)

        # Resolve hero_image to root-relative path (articles store ../images/...)
        hero_image_raw = data.get('hero_image', '')
        if hero_image_raw:
            # Convert ../images/x.jpg -> images/x.jpg for root-level template
            hero_image = hero_image_raw.replace('../', '')
        else:
            hero_image = _find_card_image(slug)

        # Find a card image (first matching image in images/)
        card_image = _find_card_image(slug) or hero_image

        episodes.append({
            'slug': slug,
            'title': data.get('title', ''),
            'deck': data.get('deck', ''),
            'location': data.get('location', ''),
            'date': data.get('date', ''),
            'hero_image': hero_image,
            'kicker': data.get('kicker', 'סיור קולינרי'),
            'card_image': card_image,
        })

    # Sort by date (DD.MM.YYYY), newest first
    def _parse_date(ep):
        try:
            return datetime.strptime(ep['date'], '%d.%m.%Y')
        except (ValueError, TypeError):
            return datetime.min

    episodes.sort(key=_parse_date, reverse=True)
    return episodes


def regenerate_homepage(episodes: list[dict]):
    """Rebuild index.html using template_homepage.html and episode metadata."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(BASE_DIR)))
    template = env.get_template('template_homepage.html')

    hero = episodes[0] if episodes else {
        'title': 'מקורב לצלחת',
        'deck': 'מסע שבועי אל השווקים, המטבחים, השדות והמעבדות של ישראל.',
        'slug': '',
        'hero_image': '',
    }

    html = template.render(hero=hero, episodes=episodes)
    out_path = BASE_DIR / 'index.html'
    out_path.write_text(html, encoding='utf-8')
    print(f'✅ Homepage regenerated: {out_path}')
    return out_path


# ── CLI ──

def cmd_transcribe(args):
    """Transcribe an audio file."""
    load_env()
    file_path = args.file
    location = args.location
    slug = slugify(location) if location else slugify(Path(file_path).stem.split(' - ')[0])

    # Check if already transcribed
    transcript_path = TRANSCRIPTS_DIR / f'{slug}.json'
    if transcript_path.exists() and not args.force:
        print(f'⏭  Transcript already exists: {transcript_path}')
        return

    print(f'🎤 Transcribing: {file_path}')

    # Convert to MP3 if needed
    if not file_path.endswith('.mp3'):
        print(f'  Converting to MP3...')
        mp3_path = convert_to_mp3(file_path)
    else:
        mp3_path = file_path

    # Transcribe
    print(f'  Sending to Whisper API...')
    transcript = transcribe(mp3_path)

    # Save
    saved = save_transcript(transcript, slug)
    print(f'✅ Saved transcript: {saved}')

    # Clean up MP3 if we created it
    if mp3_path != file_path and os.path.exists(mp3_path):
        os.remove(mp3_path)

def cmd_download(args):
    """Download episodes from Google Drive."""
    if args.list:
        print('📂 Listing episodes from Google Drive...')
        episodes = list_drive_episodes()
        if not episodes:
            print('No episodes found.')
            return
        print(f'\n{"#":<4} {"Name":<30} {"Filename":<50} {"Size (MB)":<10} {"Subfolder":<20}')
        print('-' * 114)
        for i, ep in enumerate(episodes, 1):
            size_mb = f"{ep['size'] / 1024 / 1024:.1f}"
            subfolder = ep['subfolder'] or '-'
            print(f'{i:<4} {ep["name"]:<30} {ep["filename"]:<50} {size_mb:<10} {subfolder:<20}')
        print(f'\nTotal: {len(episodes)} episodes')
    elif args.episode:
        episodes = list_drive_episodes()
        target = args.episode.lower()
        match = [ep for ep in episodes if ep['name'].lower() == target or target in ep['name'].lower()]
        if not match:
            print(f'❌ Episode not found: {args.episode}')
            print('Available:', ', '.join(ep['name'] for ep in episodes))
            sys.exit(1)
        ep = match[0]
        print(f'⬇️  Downloading: {ep["filename"]}')
        local_path = download_episode(ep)
        print(f'✅ Downloaded to: {local_path}')
    elif args.all:
        episodes = list_drive_episodes()
        print(f'⬇️  Downloading {len(episodes)} episodes...')
        for i, ep in enumerate(episodes, 1):
            print(f'  [{i}/{len(episodes)}] {ep["filename"]}')
            local_path = download_episode(ep)
            print(f'    → {local_path}')
        print(f'✅ All episodes downloaded to: {TEMP_DIR}')
    else:
        print('Error: specify --list, --episode, or --all')
        sys.exit(1)


def cmd_pipeline(args):
    """Full pipeline: download + transcribe from Google Drive."""
    load_env()
    print('📂 Listing episodes from Google Drive...')
    episodes = list_drive_episodes()
    if not episodes:
        print('No episodes found.')
        return

    if args.limit:
        episodes = episodes[:args.limit]

    transcribed = []
    skipped = []
    needs_article = []

    for i, ep in enumerate(episodes, 1):
        slug = slugify(ep['name'])
        article_path = ARTICLES_DIR / f'{slug}.json'
        transcript_path = TRANSCRIPTS_DIR / f'{slug}.json'

        # Skip if article already exists (unless --force)
        if article_path.exists() and not args.force:
            print(f'  [{i}/{len(episodes)}] ⏭  {ep["name"]} (slug: {slug}) — article exists, skipping')
            skipped.append(ep['name'])
            continue

        # Skip if already transcribed (unless --force)
        if transcript_path.exists() and not args.force:
            print(f'  [{i}/{len(episodes)}] ⏭  {ep["name"]} (slug: {slug}) — transcript exists')
            needs_article.append(slug)
            continue

        print(f'  [{i}/{len(episodes)}] ⬇️  Downloading: {ep["filename"]}')
        local_path = download_episode(ep)

        print(f'  [{i}/{len(episodes)}] 🔄 Converting to MP3...')
        mp3_path = convert_to_mp3(local_path)

        print(f'  [{i}/{len(episodes)}] 🎤 Transcribing via Whisper...')
        transcript = transcribe(mp3_path)
        save_transcript(transcript, slug)
        transcribed.append(slug)

        print(f'  [{i}/{len(episodes)}] ⏸  Article generation needed for {slug} — run manually in Claude Code')
        needs_article.append(slug)

        # Clean up temp files
        cleanup_temp(local_path)
        if mp3_path != local_path:
            cleanup_temp(mp3_path)

    # Summary
    print('\n' + '=' * 60)
    print('📊 Pipeline Summary')
    print('=' * 60)
    if transcribed:
        print(f'\n✅ Transcribed ({len(transcribed)}):')
        for slug in transcribed:
            print(f'   - {slug}')
    if skipped:
        print(f'\n⏭  Skipped — article exists ({len(skipped)}):')
        for name in skipped:
            print(f'   - {name}')
    if needs_article:
        print(f'\n📝 Needs article generation ({len(needs_article)}):')
        for slug in needs_article:
            print(f'   - {slug}')
    print()

    # Regenerate homepage with all available articles
    all_eps = collect_all_metadata()
    if all_eps:
        print('🏠 Regenerating homepage...')
        regenerate_homepage(all_eps)


def cmd_homepage(args):
    """Regenerate homepage from all article metadata."""
    episodes = collect_all_metadata()
    if not episodes:
        print('No articles found in articles/. Nothing to do.')
        return
    print(f'📄 Found {len(episodes)} episode(s). Regenerating homepage...')
    regenerate_homepage(episodes)


def cmd_render(args):
    """Render article JSON to HTML."""
    if args.all:
        ARTICLES_DIR.mkdir(exist_ok=True)
        for article_file in sorted(ARTICLES_DIR.glob('*.json')):
            slug = article_file.stem
            print(f'🖨  Rendering: {slug}')
            article = json.loads(article_file.read_text(encoding='utf-8'))
            html = render_episode_page(article)
            saved = save_episode_page(html, slug)
            print(f'✅ Saved: {saved}')
    elif args.slug:
        slug = args.slug
        print(f'🖨  Rendering: {slug}')
        article = load_article(slug)
        html = render_episode_page(article)
        saved = save_episode_page(html, slug)
        print(f'✅ Saved: {saved}')
    else:
        print('Error: specify --slug or --all')
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='מקורב לצלחת content pipeline')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # transcribe
    p_transcribe = subparsers.add_parser('transcribe', help='Transcribe audio file')
    p_transcribe.add_argument('--file', required=True, help='Path to audio file')
    p_transcribe.add_argument('--location', help='Location name (e.g. "שוק רמלה")')
    p_transcribe.add_argument('--force', action='store_true', help='Overwrite existing transcript')

    # render
    p_render = subparsers.add_parser('render', help='Render article JSON to HTML')
    p_render.add_argument('--slug', help='Episode slug to render')
    p_render.add_argument('--all', action='store_true', help='Render all articles')

    # download
    p_download = subparsers.add_parser('download', help='Download episodes from Google Drive')
    p_download.add_argument('--list', action='store_true', help='List available episodes')
    p_download.add_argument('--episode', help='Download a specific episode by name')
    p_download.add_argument('--all', action='store_true', help='Download all episodes')

    # pipeline
    p_pipeline = subparsers.add_parser('pipeline', help='Full pipeline: download + transcribe from Drive')
    p_pipeline.add_argument('--all', action='store_true', help='Process all episodes from Drive')
    p_pipeline.add_argument('--limit', type=int, help='Process only first N episodes')
    p_pipeline.add_argument('--force', action='store_true', help='Overwrite existing transcripts/articles')

    # homepage
    subparsers.add_parser('homepage', help='Regenerate homepage from all articles')

    args = parser.parse_args()

    if args.command == 'transcribe':
        cmd_transcribe(args)
    elif args.command == 'render':
        cmd_render(args)
    elif args.command == 'download':
        cmd_download(args)
    elif args.command == 'pipeline':
        cmd_pipeline(args)
    elif args.command == 'homepage':
        cmd_homepage(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
