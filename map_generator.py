#!/usr/bin/env python3
"""Generate unique hand-drawn-style SVG maps for episode articles."""

import hashlib
import math
from urllib.parse import quote


# ── Colors ──
COLORS = {
    'bg': '#2d2a26',
    'border': '#6b6560',
    'street': '#6b6560',
    'street_center': '#8a9570',
    'building_fill': '#3d3935',
    'building_stroke': '#6b705c',
    'text_light': '#f5f0e8',
    'text_muted': '#8a9570',
}

STATION_COLORS = ['#994422', '#853a00', '#6b705c']


def _seeded_values(slug: str, count: int) -> list[float]:
    """Get deterministic pseudo-random floats [0,1) from slug hash."""
    digest = hashlib.md5(slug.encode()).digest()
    values = []
    for i in range(count):
        byte_idx = i % len(digest)
        values.append(digest[byte_idx] / 255.0)
    return values


def _vary(base: float, seed: float, amplitude: float) -> float:
    """Vary a base value by seed * amplitude, centered around base."""
    return base + (seed - 0.5) * 2 * amplitude


def generate_svg_map(article: dict) -> str:
    """Generate a unique hand-drawn-style SVG map for an episode.

    Args:
        article: dict with 'stations', 'location', 'google_maps_searches'

    Returns:
        SVG string (not wrapped in any HTML container)
    """
    stations = article.get('stations', [])
    location = article.get('location', '')
    searches = article.get('google_maps_searches', [])
    slug = article.get('slug', 'default')
    n = len(stations)

    if n == 0:
        return ''

    # SVG dimensions
    W, H = 700, 500

    # Get seed values for variation
    seeds = _seeded_values(slug, 32)

    parts = []

    # ── SVG open ──
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'style="width:100%;height:auto;display:block" '
        f'font-family="\'Work Sans\', sans-serif" direction="rtl">'
    )

    # ── Background ──
    parts.append(f'<rect width="{W}" height="{H}" fill="{COLORS["bg"]}"/>')

    # ── Dashed border ──
    parts.append(
        f'<rect x="8" y="8" width="{W-16}" height="{H-16}" fill="none" '
        f'stroke="{COLORS["border"]}" stroke-width="1" stroke-dasharray="6 4" opacity="0.4"/>'
    )

    # ── Streets ──
    streets_svg = _generate_streets(W, H, n, seeds)
    parts.append(streets_svg)

    # ── Building blocks ──
    buildings_svg = _generate_buildings(W, H, n, seeds)
    parts.append(buildings_svg)

    # ── Station markers ──
    positions = _get_station_positions(W, H, n, seeds)

    for i, station in enumerate(stations):
        color = STATION_COLORS[i % len(STATION_COLORS)]
        pos = positions[i] if i < len(positions) else (W // 2, H // 2)
        search_query = searches[i] if i < len(searches) else quote(station['name'])
        maps_url = f'https://www.google.com/maps/search/{search_query}'

        marker_svg = _render_station_marker(
            pos=pos,
            number=station.get('number', i + 1),
            name=station.get('name', ''),
            descriptor=station.get('descriptor', ''),
            color=color,
            maps_url=maps_url,
            index=i,
            total=n,
            seeds=seeds,
        )
        parts.append(marker_svg)

    # ── Compass rose ──
    parts.append(_render_compass(W, H, seeds))

    # ── Location title ──
    parts.append(_render_location_title(W, H, location))

    # ── SVG close ──
    parts.append('</svg>')

    return '\n'.join(parts)


def _generate_streets(W: int, H: int, n: int, seeds: list[float]) -> str:
    """Generate hand-drawn-style streets with bezier curves."""
    parts = []
    sw = 18  # street width

    # Main horizontal street — always present
    y_main = _vary(H * 0.42, seeds[0], 30)
    cx1 = _vary(W * 0.25, seeds[1], 20)
    cy1 = _vary(y_main - 15, seeds[2], 15)
    cx2 = _vary(W * 0.75, seeds[3], 20)
    cy2 = _vary(y_main + 10, seeds[4], 15)

    main_path = f'M 20,{y_main:.0f} C {cx1:.0f},{cy1:.0f} {cx2:.0f},{cy2:.0f} {W-20},{y_main + _vary(0, seeds[5], 20):.0f}'

    # Wide street fill
    parts.append(
        f'<path d="{main_path}" fill="none" stroke="{COLORS["street"]}" '
        f'stroke-width="{sw}" stroke-linecap="round" opacity="0.7"/>'
    )
    # Dashed center line
    parts.append(
        f'<path d="{main_path}" fill="none" stroke="{COLORS["street_center"]}" '
        f'stroke-width="1.5" stroke-dasharray="8 6" stroke-linecap="round" opacity="0.5"/>'
    )

    # Cross streets
    cross_count = max(1, min(n, 3))

    for ci in range(cross_count):
        if cross_count == 1:
            cx_base = W * 0.5
        elif cross_count == 2:
            cx_base = W * (0.35 + ci * 0.3)
        else:
            cx_base = W * (0.25 + ci * 0.25)

        cx_x = _vary(cx_base, seeds[6 + ci], 25)
        top_y = _vary(30, seeds[9 + ci], 15)
        bot_y = _vary(H - 30, seeds[12 + ci], 15)

        # Slight curve for hand-drawn feel
        mid_x = _vary(cx_x, seeds[15 + ci], 18)

        cross_path = (
            f'M {cx_x:.0f},{top_y:.0f} '
            f'Q {mid_x:.0f},{H * 0.5:.0f} {cx_x + _vary(0, seeds[18 + ci], 12):.0f},{bot_y:.0f}'
        )

        parts.append(
            f'<path d="{cross_path}" fill="none" stroke="{COLORS["street"]}" '
            f'stroke-width="{sw - 4}" stroke-linecap="round" opacity="0.5"/>'
        )
        parts.append(
            f'<path d="{cross_path}" fill="none" stroke="{COLORS["street_center"]}" '
            f'stroke-width="1" stroke-dasharray="6 5" stroke-linecap="round" opacity="0.35"/>'
        )

    # Optional alley for 3+ stations
    if n >= 3:
        alley_x1 = _vary(W * 0.6, seeds[21], 30)
        alley_y1 = _vary(H * 0.55, seeds[22], 20)
        alley_x2 = _vary(W * 0.75, seeds[23], 20)
        alley_y2 = _vary(H * 0.8, seeds[24], 20)

        parts.append(
            f'<path d="M {alley_x1:.0f},{alley_y1:.0f} L {alley_x2:.0f},{alley_y2:.0f}" '
            f'fill="none" stroke="{COLORS["street"]}" '
            f'stroke-width="8" stroke-linecap="round" opacity="0.35"/>'
        )

    return '\n'.join(parts)


def _generate_buildings(W: int, H: int, n: int, seeds: list[float]) -> str:
    """Generate subtle rectangular building blocks."""
    parts = []

    # Number of buildings depends on station count
    base_count = 4 + n * 2
    # Use seeds to place buildings
    building_seeds = _seeded_values(f"buildings-{n}", base_count * 4)

    # Define zones to avoid (near center where stations go) — we'll be approximate
    for i in range(base_count):
        si = i * 4
        bx = 30 + building_seeds[si % len(building_seeds)] * (W - 100)
        by = 30 + building_seeds[(si + 1) % len(building_seeds)] * (H - 100)
        bw = 25 + building_seeds[(si + 2) % len(building_seeds)] * 40
        bh = 18 + building_seeds[(si + 3) % len(building_seeds)] * 30
        rotation = (building_seeds[si % len(building_seeds)] - 0.5) * 6

        parts.append(
            f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bw:.0f}" height="{bh:.0f}" '
            f'fill="{COLORS["building_fill"]}" stroke="{COLORS["building_stroke"]}" '
            f'stroke-width="0.5" opacity="0.4" '
            f'transform="rotate({rotation:.1f} {bx + bw / 2:.0f} {by + bh / 2:.0f})"/>'
        )

    return '\n'.join(parts)


def _get_station_positions(W: int, H: int, n: int, seeds: list[float]) -> list[tuple]:
    """Calculate station marker positions based on count."""
    positions = []

    if n == 1:
        x = _vary(W * 0.5, seeds[0], 30)
        y = _vary(H * 0.42, seeds[1], 15)
        positions.append((x, y))

    elif n == 2:
        x1 = _vary(W * 0.3, seeds[0], 20)
        y1 = _vary(H * 0.38, seeds[1], 15)
        x2 = _vary(W * 0.7, seeds[2], 20)
        y2 = _vary(H * 0.42, seeds[3], 15)
        positions.append((x1, y1))
        positions.append((x2, y2))

    elif n == 3:
        x1 = _vary(W * 0.22, seeds[0], 15)
        y1 = _vary(H * 0.38, seeds[1], 12)
        x2 = _vary(W * 0.50, seeds[2], 15)
        y2 = _vary(H * 0.36, seeds[3], 12)
        x3 = _vary(W * 0.72, seeds[4], 15)
        y3 = _vary(H * 0.58, seeds[5], 15)
        positions.append((x1, y1))
        positions.append((x2, y2))
        positions.append((x3, y3))

    else:
        # 4+ stations: distribute along streets
        for i in range(n):
            frac = (i + 0.5) / n
            x = _vary(W * (0.15 + frac * 0.7), seeds[i % len(seeds)], 15)
            if i % 2 == 0:
                y = _vary(H * 0.38, seeds[(i + 1) % len(seeds)], 15)
            else:
                y = _vary(H * 0.55, seeds[(i + 1) % len(seeds)], 15)
            positions.append((x, y))

    return positions


def _render_station_marker(
    pos: tuple,
    number: int,
    name: str,
    descriptor: str,
    color: str,
    maps_url: str,
    index: int,
    total: int,
    seeds: list[float],
) -> str:
    """Render a single station marker with circle, connector, and label box."""
    px, py = pos
    parts = []

    # Label box position — alternate above/below based on index
    label_w = 160
    label_h = 52
    if index % 2 == 0:
        # Label above
        label_y = py - 85 - _vary(0, seeds[index % len(seeds)], 10)
    else:
        # Label below
        label_y = py + 35 + _vary(0, seeds[index % len(seeds)], 10)

    # Center label horizontally on marker, but clamp to SVG bounds
    label_x = max(15, min(px - label_w / 2, 700 - label_w - 15))

    label_cx = label_x + label_w / 2
    if index % 2 == 0:
        label_conn_y = label_y + label_h
    else:
        label_conn_y = label_y

    # Open clickable group
    parts.append(
        f'<a href="{maps_url}" target="_blank" style="cursor:pointer">'
    )

    # Connector line from circle to label
    parts.append(
        f'<line x1="{px:.0f}" y1="{py:.0f}" x2="{label_cx:.0f}" y2="{label_conn_y:.0f}" '
        f'stroke="{color}" stroke-width="1.5" opacity="0.6" stroke-dasharray="3 2"/>'
    )

    # Circle marker
    parts.append(
        f'<circle cx="{px:.0f}" cy="{py:.0f}" r="14" fill="{color}" opacity="0.9"/>'
    )
    parts.append(
        f'<circle cx="{px:.0f}" cy="{py:.0f}" r="14" fill="none" '
        f'stroke="{COLORS["text_light"]}" stroke-width="1.5" opacity="0.3"/>'
    )

    # Number inside circle
    parts.append(
        f'<text x="{px:.0f}" y="{py + 5:.0f}" text-anchor="middle" '
        f'fill="{COLORS["text_light"]}" font-size="13" font-weight="700" '
        f'font-family="\'Work Sans\', sans-serif">{number}</text>'
    )

    # Label box background
    parts.append(
        f'<rect x="{label_x:.0f}" y="{label_y:.0f}" width="{label_w}" height="{label_h}" '
        f'rx="3" fill="{COLORS["bg"]}" stroke="{color}" stroke-width="1.5" opacity="0.95"/>'
    )

    # Station name (serif)
    name_y = label_y + 22
    parts.append(
        f'<text x="{label_x + label_w / 2:.0f}" y="{name_y:.0f}" text-anchor="middle" '
        f'fill="{COLORS["text_light"]}" font-size="14" font-weight="600" '
        f'font-family="\'Newsreader\', serif">{_escape_xml(name)}</text>'
    )

    # Descriptor (sans-serif, muted)
    desc_y = label_y + 40
    # Truncate long descriptors
    desc_text = descriptor if len(descriptor) <= 30 else descriptor[:28] + '...'
    parts.append(
        f'<text x="{label_x + label_w / 2:.0f}" y="{desc_y:.0f}" text-anchor="middle" '
        f'fill="{COLORS["text_muted"]}" font-size="10" font-weight="400" '
        f'font-family="\'Work Sans\', sans-serif">{_escape_xml(desc_text)}</text>'
    )

    # Close clickable group
    parts.append('</a>')

    return '\n'.join(parts)


def _render_compass(W: int, H: int, seeds: list[float]) -> str:
    """Render a simple compass rose in the top-left corner."""
    cx, cy = 45, 45
    size = 16

    parts = []
    parts.append(f'<g opacity="0.5">')

    # North arrow
    parts.append(
        f'<line x1="{cx}" y1="{cy + size}" x2="{cx}" y2="{cy - size}" '
        f'stroke="{COLORS["text_muted"]}" stroke-width="1.2"/>'
    )
    # Arrowhead
    parts.append(
        f'<polygon points="{cx},{cy - size - 4} {cx - 4},{cy - size + 4} {cx + 4},{cy - size + 4}" '
        f'fill="{COLORS["text_muted"]}"/>'
    )
    # N label
    parts.append(
        f'<text x="{cx}" y="{cy - size - 8}" text-anchor="middle" '
        f'fill="{COLORS["text_muted"]}" font-size="10" font-weight="600" '
        f'font-family="\'Work Sans\', sans-serif">N</text>'
    )
    # Small cross
    parts.append(
        f'<line x1="{cx - size * 0.5}" y1="{cy}" x2="{cx + size * 0.5}" y2="{cy}" '
        f'stroke="{COLORS["text_muted"]}" stroke-width="0.8"/>'
    )

    parts.append('</g>')
    return '\n'.join(parts)


def _render_location_title(W: int, H: int, location: str) -> str:
    """Render location title and subtitle in bottom corner."""
    parts = []

    # Location name
    parts.append(
        f'<text x="{W - 25}" y="{H - 35}" text-anchor="end" '
        f'fill="{COLORS["text_light"]}" font-size="16" font-weight="700" '
        f'font-family="\'Work Sans\', sans-serif" opacity="0.7">{_escape_xml(location)}</text>'
    )

    # Subtitle
    parts.append(
        f'<text x="{W - 25}" y="{H - 18}" text-anchor="end" '
        f'fill="{COLORS["text_muted"]}" font-size="9" font-weight="400" '
        f'font-family="\'Work Sans\', sans-serif" opacity="0.5">'
        f'\u05de\u05e4\u05d4 \u05e1\u05db\u05de\u05d8\u05d9\u05ea \u00b7 '
        f'\u05dc\u05d0 \u05d1\u05e7\u05e0\u05d4 \u05de\u05d9\u05d3\u05d4</text>'
    )

    return '\n'.join(parts)


def _escape_xml(text: str) -> str:
    """Escape text for XML/SVG content."""
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )
