#!/usr/bin/env python3
"""Content pipeline for מקורב לצלחת website."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
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

def slugify(name: str) -> str:
    """Convert episode name to URL slug.
    'שוק רמלה' → 'ramle'
    'Gay Friendly Jerusalem' → 'gay-friendly-jerusalem'
    """
    # For Hebrew names, transliterate manually would be complex.
    # Use a simple approach: lowercase, replace spaces with hyphens, strip non-alphanum
    import re
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')
    return slug

def convert_to_mp3(input_path: str) -> str:
    """Convert audio to MP3 64kbps mono using ffmpeg. Returns MP3 path."""
    mp3_path = input_path.rsplit('.', 1)[0] + '.mp3'
    if input_path.endswith('.mp3'):
        return input_path
    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-codec:a', 'libmp3lame', '-b:a', '64k', '-ac', '1',
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

    args = parser.parse_args()

    if args.command == 'transcribe':
        cmd_transcribe(args)
    elif args.command == 'render':
        cmd_render(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
