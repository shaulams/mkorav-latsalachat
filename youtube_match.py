#!/usr/bin/env python3
"""YouTube playlist matching for מקורב לצלחת episodes."""

import subprocess
import json
from difflib import SequenceMatcher

YOUTUBE_PLAYLIST = "https://www.youtube.com/playlist?list=PLKU94MaFRcfL7abNx0eQPLS8vG2VvsbV7"

# Transliteration map for Israeli cities
CITY_TRANSLITERATIONS = {
    "afula": "עפולה",
    "akko": "עכו",
    "arad": "ערד",
    "ashdod": "אשדוד",
    "ashkelon": "אשקלון",
    "bat galim": "בת גלים",
    "bat yam": "בת ים",
    "beit israel": "בית ישראל",
    "beit shean": "בית שאן",
    "bnei brak": "בני ברק",
    "jaffa": "יפו",
    "levinski": "לוינסקי",
    "nazereth": "נצרת",
    "nazareth": "נצרת",
    "netibot": "נתיבות",
    "netivot": "נתיבות",
    "pardes": "פרדס",
    "ramle": "רמלה",
    "rehovot": "רחובות",
    "tiberias": "טבריה",
    "tzfat": "צפת",
    "wadi ara": "ואדי ערה",
    "gay friendly jerusalem": "ירושלים",
    "farmer's market": "שוק האיכרים",
    "hisda": "חסדא",
    "mango": "מנגו",
    "mustard": "חרדל",
    "bakaa": "בקעה",
    "lehemke": "לחמקה",
    "israeli coffee": "קפה",
}


def fetch_youtube_playlist() -> list[dict]:
    """Use yt-dlp to get all videos from the playlist.

    Runs: yt-dlp --flat-playlist --print "%(id)s|||%(title)s|||%(duration)s" {PLAYLIST_URL}

    Returns list of dicts: [{"id": "Tl5LILGBNJc", "title": "...", "duration": 123}]
    """
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print",
            "%(id)s|||%(title)s|||%(duration)s",
            YOUTUBE_PLAYLIST,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|||")
        if len(parts) >= 3:
            vid_id, title, duration_str = parts[0], parts[1], parts[2]
            try:
                duration = int(float(duration_str)) if duration_str and duration_str != "NA" else 0
            except (ValueError, TypeError):
                duration = 0
            videos.append({"id": vid_id, "title": title, "duration": duration})
    return videos


def match_episode_to_youtube(episode_name: str, videos: list[dict]) -> str | None:
    """Match an episode name to a YouTube video.

    Strategy:
    1. Try exact substring match (episode name appears in video title)
    2. Try Hebrew transliteration substring match
    3. Try fuzzy match using SequenceMatcher (threshold: 0.5)
    4. Return the youtube video ID if matched, None otherwise
    """
    name_lower = episode_name.lower().strip()

    # Get Hebrew equivalent if available
    hebrew_name = CITY_TRANSLITERATIONS.get(name_lower)

    # 1. Exact substring match (English name in video title)
    for video in videos:
        title_lower = video["title"].lower()
        if name_lower in title_lower:
            return video["id"]

    # 2. Hebrew transliteration substring match
    if hebrew_name:
        for video in videos:
            if hebrew_name in video["title"]:
                return video["id"]

    # 3. Fuzzy match — try both English and Hebrew names against video titles
    best_ratio = 0.0
    best_id = None

    for video in videos:
        title = video["title"]
        # Strip common prefix for better matching
        clean_title = title.replace("מקורב לצלחת", "").strip(" -–—")

        # Compare English name
        ratio = SequenceMatcher(None, name_lower, clean_title.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = video["id"]

        # Compare Hebrew name
        if hebrew_name:
            ratio = SequenceMatcher(None, hebrew_name, clean_title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = video["id"]

    if best_ratio >= 0.5:
        return best_id

    return None


def match_all_episodes(episode_names: list[str]) -> dict[str, str | None]:
    """Match all episodes to YouTube videos.

    Returns dict: {"ramle": "Tl5LILGBNJc", "afula": "abc123", "unknown": None}
    """
    videos = fetch_youtube_playlist()
    results = {}
    for name in episode_names:
        slug = name.lower().strip()
        yt_id = match_episode_to_youtube(name, videos)
        results[slug] = yt_id
    return results


if __name__ == "__main__":
    """Test: fetch playlist and print all videos."""
    videos = fetch_youtube_playlist()
    print(f"Found {len(videos)} videos:")
    for v in videos:
        print(f"  {v['id']} | {v['title']}")
