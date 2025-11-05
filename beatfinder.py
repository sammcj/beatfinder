#!/usr/bin/env python3
"""
BeatFinder - Discover new artists based on your Apple Music library
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from apple_music_integration import create_apple_music_playlist_with_scraping
from apple_music_web_api import create_beatfinder_playlist
from config import (
    APPLE_EXPORT_DIR,
    AM_SCRAPE_BATCH_SIZE,
    CACHE_DIR,
    CREATE_PLAYLIST,
    CLI_INTERACTIVE_FILTERING,
    HTML_VISUALISATION,
    LASTFM_API_KEY,
    MAX_ARTIST_LISTENERS,
    MAX_RECOMMENDATIONS,
    PLAYLIST_MERGE_MODE,
    PLAYLIST_SKIP_LIBRARY_CHECK,
    PLAYLIST_SONGS_PER_ARTIST,
    RARITY_PREFERENCE,
    USE_APPLE_EXPORT,
    show_config,
)
from interactive_filter import (
    filter_rejected_from_recommendations,
    show_interactive_filter,
)
from library_parser import AppleMusicLibrary
from apple_export_parser import AppleMusicExportParser
from recommendation_engine import (
    LastFmClient,
    RecommendationEngine,
    load_recommendations_cache,
    save_recommendations_cache,
)


def format_recommendations(recommendations: List[Dict], limit: int, artist_music_data: Dict[str, Dict] = None, library_stats: Dict = None) -> str:
    """Format recommendations as markdown with optional Apple Music links and library statistics"""
    output = ["# BeatFinder Recommendations\n"]
    output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    output.append(f"Total recommendations: {len(recommendations)}\n")

    # Add library statistics if available
    if library_stats:
        output.append("\n## Library Statistics\n")

        if library_stats.get("oldest_play") and library_stats.get("history_span_years"):
            output.append(f"**Listening History:** {library_stats['history_span_years']} years ({library_stats.get('oldest_play')} - {library_stats.get('newest_play')})\n")

        if library_stats.get("total_artists"):
            output.append(f"**Total Artists:** {library_stats['total_artists']:,}\n")

        if library_stats.get("total_plays"):
            output.append(f"**Total Plays:** {library_stats['total_plays']:,}\n")

        if library_stats.get("skip_rate") is not None:
            output.append(f"**Skip Rate:** {library_stats['skip_rate']:.1f}%\n")

        if library_stats.get("loved_artists"):
            output.append(f"**Loved Artists:** {library_stats['loved_artists']:,}\n")

        if library_stats.get("disliked_artists"):
            output.append(f"**Disliked Artists:** {library_stats['disliked_artists']:,}\n")

    output.append("\n---\n")

    for i, rec in enumerate(recommendations[:limit], 1):
        output.append(f"\n## {i}. {rec['name']}\n")
        output.append(f"**Score:** {rec['score']:.3f} | ")
        output.append(f"**Listeners:** {rec['listeners']:,} | ")
        output.append(f"**Rarity:** {rec['rarity_score']:.3f}\n")
        output.append(f"\n**Recommended by ({rec['frequency']} artists):**\n")
        for artist in rec['recommended_by'][:5]:
            output.append(f"- {artist}\n")
        if len(rec['recommended_by']) > 5:
            output.append(f"- ...and {len(rec['recommended_by']) - 5} more\n")

        if rec['tags']:
            output.append(f"\n**Tags:** {', '.join(rec['tags'][:5])}\n")

        # Apple Music links from scraping data
        artist_name = rec['name']
        if artist_music_data and artist_name in artist_music_data:
            artist_data = artist_music_data[artist_name]
            artist_url = artist_data.get('artist_url')
            songs = artist_data.get('songs', [])

            if artist_url:
                output.append(f"\n[View in Apple Music]({artist_url})\n")

            if songs:
                output.append(f"\n**Top Songs:**\n")
                for song in songs[:3]:
                    song_title = song['title']
                    song_url = song.get('web_url', artist_url)
                    output.append(f"- [{song_title}]({song_url})\n")
        else:
            # Fallback to search link
            search_url = f"music://music.apple.com/search?term={artist_name.replace(' ', '+')}"
            output.append(f"\n[Search in Apple Music]({search_url})\n")

        output.append("\n---\n")

    return "".join(output)


def HTML_VISUALISATION(recommendations: List[Dict], loved_artists: List[str], limit: int, artist_music_data: Dict[str, Dict] = None, library_stats: Dict = None) -> bool:
    """
    Generate an interactive HTML visualisation showing recommendation connections

    Args:
        recommendations: List of recommendation dicts
        loved_artists: List of loved artist names
        limit: Number of recommendations to include
        artist_music_data: Optional dict mapping artist names to scraped Apple Music data
        library_stats: Optional dict with library statistics (from Apple Music export)

    Returns:
        True if successful, False otherwise
    """
    if not HTML_VISUALISATION:
        return False

    output_file = Path("recommendations_visualisation.html")
    print(f"\nGenerating HTML visualisation: '{output_file.name}'...")

    # Prepare data for visualisation
    nodes = []
    edges = []
    node_ids = {}
    node_id_counter = 0

    # First pass: determine which loved artists will actually have visible edges
    artists_with_edges = set()
    for rec in recommendations[:limit]:
        visible_recommenders = [r for r in rec["recommended_by"] if r in loved_artists]
        artists_with_edges.update(visible_recommenders[:3])

    # Only add loved artists that have at least one visible edge
    for artist in loved_artists:
        if artist in artists_with_edges:
            node_ids[artist] = node_id_counter
            nodes.append({
                "id": node_id_counter,
                "label": artist,
                "group": "loved",
                "title": f"{artist}<br>Your Library",
                "value": 8,
                "font": {"bold": False}
            })
            node_id_counter += 1

    # Add recommended artists as nodes and create edges
    for idx, rec in enumerate(recommendations[:limit], 1):
        artist_name = rec["name"]
        node_ids[artist_name] = node_id_counter

        visible_recommenders = [r for r in rec["recommended_by"] if r in node_ids]
        total_in_library = len([r for r in rec["recommended_by"] if r in loved_artists])
        show_count = min(3, len(visible_recommenders))

        tooltip_extra = f" (+{total_in_library - 3} more, click for details)" if total_in_library > 3 else ""
        tooltip = f"""
        <b>{artist_name}</b><br>
        Score: {rec['score']:.2f}<br>
        Listeners: {rec['listeners']:,}<br>
        Recommended by: {rec['frequency']} artists{tooltip_extra}<br>
        Tags: {', '.join(rec['tags'][:5])}
        """

        label_extra = f"\n(+{total_in_library - 3} more)" if total_in_library > 3 else ""
        node_label = f"{artist_name}{label_extra}"

        nodes.append({
            "id": node_id_counter,
            "label": node_label,
            "group": "recommended",
            "title": tooltip.strip(),
            "value": rec['score'] * 15,
            "font": {"bold": True},
            "data": {
                "score": rec['score'],
                "listeners": rec['listeners'],
                "rarity": rec['rarity_score'],
                "frequency": rec['frequency'],
                "tags": rec['tags'][:8],
                "recommended_by": rec['recommended_by'][:10],
                "total_recommenders": total_in_library
            }
        })

        for recommender in visible_recommenders[:show_count]:
            edges.append({
                "from": node_ids[recommender],
                "to": node_id_counter,
                "title": f"{recommender} → {artist_name}"
            })

        node_id_counter += 1

    # Build library stats HTML if available
    library_stats_html = ""
    if library_stats:
        stats_parts = []

        if library_stats.get("oldest_play") and library_stats.get("history_span_years"):
            stats_parts.append(f"<strong>Listening History:</strong> {library_stats['history_span_years']} years ({library_stats.get('oldest_play')} - {library_stats.get('newest_play')})")

        if library_stats.get("total_artists"):
            stats_parts.append(f"<strong>Total Artists:</strong> {library_stats['total_artists']:,}")

        if library_stats.get("total_plays"):
            stats_parts.append(f"<strong>Total Plays:</strong> {library_stats['total_plays']:,}")

        if library_stats.get("skip_rate") is not None:
            stats_parts.append(f"<strong>Skip Rate:</strong> {library_stats['skip_rate']:.1f}%")

        if library_stats.get("loved_artists"):
            stats_parts.append(f"<strong>Loved Artists:</strong> {library_stats['loved_artists']:,}")

        if library_stats.get("disliked_artists"):
            stats_parts.append(f"<strong>Disliked Artists:</strong> {library_stats['disliked_artists']:,}")

        if stats_parts:
            library_stats_html = '<div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #ddd; width: 100%; font-size: 13px; color: #666; line-height: 1.8;">' + ' • '.join(stats_parts) + '</div>'

    # Build table rows HTML
    table_rows_html = ""
    for idx, rec in enumerate(recommendations[:limit], 1):
        artist_name = rec["name"]
        score = rec["score"]
        listeners = rec["listeners"]
        rarity = rec["rarity_score"]
        frequency = rec["frequency"]
        tags = rec.get("tags", [])[:5]
        recommenders = rec["recommended_by"][:5]

        # Apple Music links from scraping data
        music_link_html = ""
        if artist_music_data and artist_name in artist_music_data:
            artist_data = artist_music_data[artist_name]
            artist_url = artist_data.get('artist_url')
            songs = artist_data.get('songs', [])

            if artist_url:
                # Convert https:// to music:// protocol
                music_protocol_url = artist_url.replace('https://music.apple.com', 'music://')
                music_link_html = f'<a href="{music_protocol_url}" class="link">🎵 Artist</a>'

                if songs:
                    music_link_html += '<br>'
                    for i, song in enumerate(songs[:2], 1):
                        # Use music:// protocol URL instead of web URL
                        song_url = song.get('url', music_protocol_url)
                        song_title = song['title'][:20] + '...' if len(song['title']) > 20 else song['title']
                        music_link_html += f'<a href="{song_url}" class="link song-link" title="{song["title"]}">{i}. {song_title}</a><br>'

        if not music_link_html:
            search_url = f"music://music.apple.com/search?term={artist_name.replace(' ', '+')}"
            music_link_html = f'<a href="{search_url}" class="link">🎵 Search</a>'

        tags_html = " ".join([f'<span class="tag">{tag}</span>' for tag in tags])

        recommenders_text = ", ".join(recommenders)
        if len(rec["recommended_by"]) > 5:
            recommenders_text += f" ...and {len(rec['recommended_by']) - 5} more"

        table_rows_html += f"""
                <tr>
                    <td class="rank">{idx}</td>
                    <td><strong>{artist_name}</strong></td>
                    <td class="score">{score:.3f}</td>
                    <td>{listeners:,}</td>
                    <td>{rarity:.3f}</td>
                    <td class="recommenders">{recommenders_text}</td>
                    <td class="tags">{tags_html}</td>
                    <td>{music_link_html}</td>
                </tr>"""

    # Generate HTML with embedded vis.js
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>BeatFinder Recommendations Visualisation</title>
    <script src="https://unpkg.com/vis-network@9.1.2/dist/vis-network.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .info {{
            background: white;
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 20px;
        }}
        .info > p {{
            margin: 0;
        }}
        .info-title {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
            margin: 0;
        }}
        #network {{
            width: 100%;
            height: 1040px;
            border: 1px solid #ddd;
            border-radius: 8px;
            background: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .legend {{
            display: flex;
            gap: 20px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 50%;
            border: 2px solid #666;
        }}
        .loved {{ background: #4a90e2; }}
        .recommended {{ background: #7bc043; }}

        .recommendations-table {{
            margin: 40px auto;
            max-width: 1400px;
            padding: 0 20px;
        }}
        .recommendations-table h2 {{
            margin-bottom: 20px;
            color: #333;
        }}
        table {{
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-collapse: collapse;
        }}
        thead {{
            background: #4a90e2;
            color: white;
        }}
        th {{
            padding: 12px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .rank {{
            font-weight: 600;
            color: #666;
            width: 50px;
        }}
        .score {{
            font-weight: 600;
            color: #7bc043;
        }}
        .tag {{
            display: inline-block;
            background: #e8f5e9;
            color: #2e7d32;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 12px;
            margin: 2px;
        }}
        .link {{
            color: #4a90e2;
            text-decoration: none;
        }}
        .link:hover {{
            text-decoration: underline;
        }}
        .song-link {{
            font-size: 11px;
            display: block;
            margin: 2px 0;
        }}
        .recommenders {{
            color: #666;
            font-size: 13px;
        }}
        .footer {{
            text-align: center;
            padding: 40px 20px;
            color: #666;
            font-size: 14px;
        }}
        .footer a {{
            color: #4a90e2;
            text-decoration: none;
        }}
        .footer a:hover {{
            text-decoration: underline;
        }}

        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }}
        .modal-content {{
            background-color: white;
            margin: 10% auto;
            padding: 30px;
            border-radius: 8px;
            width: 90%;
            max-width: 600px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .close {{
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            line-height: 1;
        }}
        .close:hover {{
            color: #000;
        }}
        .modal h2 {{
            margin-top: 0;
            color: #333;
        }}
        .modal-section {{
            margin: 20px 0;
        }}
        .modal-section h3 {{
            color: #4a90e2;
            font-size: 16px;
            margin-bottom: 10px;
        }}
        .modal-list {{
            list-style: none;
            padding: 0;
        }}
        .modal-list li {{
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }}
        .modal-button {{
            display: inline-block;
            background: #4a90e2;
            color: white;
            padding: 10px 20px;
            border-radius: 4px;
            text-decoration: none;
            margin-top: 15px;
        }}
        .modal-button:hover {{
            background: #357abd;
        }}
    </style>
</head>
<body>
    <div class="info">
        <h1 class="info-title">BeatFinder Recommendations</h1>
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color loved"></div>
                <span>Your Library</span>
            </div>
            <div class="legend-item">
                <div class="legend-color recommended"></div>
                <span>Recommendations</span>
            </div>
        </div>
        <p>Click any node for details</p>
        {library_stats_html}
    </div>

    <div id="network"></div>

    <div id="nodeModal" class="modal">
        <div class="modal-content">
            <span class="close">&times;</span>
            <div id="modalBody"></div>
        </div>
    </div>

    <div class="recommendations-table">
        <h2>Full Recommendation List</h2>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Artist</th>
                    <th>Score</th>
                    <th>Listeners</th>
                    <th>Rarity</th>
                    <th>Recommended By</th>
                    <th>Tags</th>
                    <th>Apple Music</th>
                </tr>
            </thead>
            <tbody>
{table_rows_html}
            </tbody>
        </table>
    </div>

    <script>
        const nodes = new vis.DataSet({json.dumps(nodes)});
        const edges = new vis.DataSet({json.dumps(edges)});

        const options = {{
            nodes: {{
                shape: 'dot',
                borderWidth: 2,
                shadow: true,
                font: {{
                    size: 14,
                    color: '#333'
                }}
            }},
            edges: {{
                width: 2,
                color: {{
                    color: '#cccccc',
                    highlight: '#4a90e2',
                    hover: '#4a90e2'
                }},
                smooth: {{
                    type: 'continuous',
                    roundness: 0.5
                }},
                arrows: {{
                    to: {{
                        enabled: true,
                        scaleFactor: 0.5
                    }}
                }}
            }},
            groups: {{
                loved: {{
                    color: {{
                        background: '#4a90e2',
                        border: '#2e5fa3',
                        highlight: {{
                            background: '#2e5fa3',
                            border: '#1d3f73'
                        }}
                    }}
                }},
                recommended: {{
                    color: {{
                        background: '#7bc043',
                        border: '#5a9032',
                        highlight: {{
                            background: '#5a9032',
                            border: '#3d6022'
                        }}
                    }}
                }}
            }},
            physics: {{
                stabilization: {{
                    iterations: 200,
                    fit: true
                }},
                barnesHut: {{
                    gravitationalConstant: -8000,
                    centralGravity: 0.3,
                    springLength: 150,
                    springConstant: 0.04,
                    damping: 0.5,
                    avoidOverlap: 0.5
                }}
            }},
            interaction: {{
                hover: true,
                navigationButtons: true,
                keyboard: true
            }}
        }};

        const container = document.getElementById('network');
        const data = {{ nodes: nodes, edges: edges }};
        const network = new vis.Network(container, data, options);

        const modal = document.getElementById('nodeModal');
        const modalBody = document.getElementById('modalBody');
        const closeBtn = document.getElementsByClassName('close')[0];

        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                const nodeId = params.nodes[0];
                const node = nodes.get(nodeId);

                const searchUrl = `music://music.apple.com/search?term=${{encodeURIComponent(node.label)}}`;

                if (node.group === 'loved') {{
                    modalBody.innerHTML = `
                        <h2>${{node.label}}</h2>
                        <div class="modal-section">
                            <p>This artist is in your loved artists collection and contributed to these recommendations.</p>
                        </div>
                        <a href="${{searchUrl}}" class="modal-button">🎵 Search in Apple Music</a>
                    `;
                }} else if (node.group === 'recommended') {{
                    const tags = node.data.tags.map(t => `<span class="tag">${{t}}</span>`).join(' ');
                    const recommenders = node.data.recommended_by.map(r => `<li>${{r}}</li>`).join('');
                    const totalRec = node.data.total_recommenders;
                    const extraCount = totalRec > 10 ? ` (showing 10 of ${{totalRec}})` : '';

                    modalBody.innerHTML = `
                        <h2>${{node.label}}</h2>
                        <div class="modal-section">
                            <div><strong>Score:</strong> ${{node.data.score.toFixed(3)}}</div>
                            <div><strong>Listeners:</strong> ${{node.data.listeners.toLocaleString()}}</div>
                            <div><strong>Rarity:</strong> ${{node.data.rarity.toFixed(3)}}</div>
                            <div><strong>Recommended by:</strong> ${{node.data.frequency}} artists</div>
                        </div>
                        <div class="modal-section">
                            <h3>Tags</h3>
                            <div>${{tags}}</div>
                        </div>
                        <div class="modal-section">
                            <h3>Recommended By${{extraCount}}</h3>
                            <ul class="modal-list">${{recommenders}}</ul>
                        </div>
                        <a href="${{searchUrl}}" class="modal-button">🎵 Search in Apple Music</a>
                    `;
                }}

                modal.style.display = 'block';
            }}
        }});

        closeBtn.onclick = function() {{
            modal.style.display = 'none';
        }};

        window.onclick = function(event) {{
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }};
    </script>

    <div class="footer">
        Generated by <a href="https://github.com/sammcj/beatfinder" target="_blank">BeatFinder</a>
        • <a href="https://smcleod.net" target="_blank">smcleod.net</a>
    </div>
</body>
</html>"""

    try:
        output_file.write_text(html_content)
        print(f"✓ HTML visualisation saved to: {output_file}")
        print(f"  Open {output_file} in your browser to view the interactive graph")
        return True
    except Exception as e:
        print(f"Error generating HTML visualisation: {e}")
        return False


def get_library_parser():
    """
    Get the appropriate library parser based on configuration

    Returns:
        AppleMusicExportParser if USE_APPLE_EXPORT is True, otherwise AppleMusicLibrary
    """
    if USE_APPLE_EXPORT:
        if not APPLE_EXPORT_DIR:
            print("\nError: USE_APPLE_EXPORT is enabled but APPLE_EXPORT_DIR is not set")
            print("Please set APPLE_EXPORT_DIR in your .env file to point to the 'Apple Music Activity' folder")
            sys.exit(1)
        return AppleMusicExportParser(APPLE_EXPORT_DIR)
    else:
        return AppleMusicLibrary()


def save_run_to_history(limit: int, rarity: int, recommendations_count: int):
    """Save run to history file for web UI"""
    try:
        run_history_file = Path("data/run_history.json")
        run_history_file.parent.mkdir(exist_ok=True)

        # Load existing history
        if run_history_file.exists():
            with open(run_history_file, 'r') as f:
                history = json.load(f)
        else:
            history = []

        # Add new run
        run = {
            'id': len(history) + 1,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'recommendations_count': recommendations_count,
            'settings': {
                'rarity': rarity,
                'max_recommendations': limit,
                'enable_tag_similarity': False,  # CLI doesn't expose these
                'enable_play_frequency_weighting': False,
                'time_filter': '',
            },
            'source': 'CLI'  # Mark as CLI run
        }

        history.insert(0, run)  # Add to beginning (most recent first)

        # Keep only last 50 runs
        history = history[:50]

        # Save
        with open(run_history_file, 'w') as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        # Don't fail the whole run if history saving fails
        print(f"Warning: Could not save run history: {e}")


def main():
    parser = argparse.ArgumentParser(description="Discover new artists based on your Apple Music library")
    parser.add_argument("--scan-library", action="store_true", help="Force re-scan of Music library (slow)")
    parser.add_argument("--refresh-cache", action="store_true", help="Refresh Last.fm metadata cache (keeps recommendations cache)")
    parser.add_argument("--refresh-recommendations", action="store_true", help="Regenerate recommendations (keeps Last.fm cache)")
    parser.add_argument("--refresh-all", action="store_true", help="Clear all caches (Last.fm + recommendations)")
    parser.add_argument("--clear-rejected", action="store_true", help="Clear rejected artists cache")
    parser.add_argument("--no-interactive", action="store_true", help="Disable interactive filtering for this run")
    parser.add_argument("--regenerate-html", action="store_true", help="Regenerate HTML visualisation from cached recommendations")
    parser.add_argument("--limit", type=int, default=MAX_RECOMMENDATIONS, help="Number of recommendations")
    parser.add_argument("--rarity", type=int, choices=range(1, 16), default=RARITY_PREFERENCE,
                       help="Rarity preference: 1 (most popular) to 15 (most obscure), default: 7")
    args = parser.parse_args()

    # Validate API key
    if not LASTFM_API_KEY or LASTFM_API_KEY == "your_api_key_here":
        print("Error: Last.fm API key not configured")
        print("1. Get an API key from: https://www.last.fm/api/account/create")
        print("2. Copy .env.example to .env")
        print("3. Add your API key to .env")
        sys.exit(1)

    # Show configuration
    show_config()

    # Clear caches if requested
    if args.refresh_all or args.refresh_cache:
        lastfm_cache = CACHE_DIR / "lastfm_cache.json"
        if lastfm_cache.exists():
            lastfm_cache.unlink()
            print("Last.fm cache cleared")

    if args.refresh_all or args.refresh_recommendations:
        recommendations_cache = CACHE_DIR / "recommendations_cache.json"
        if recommendations_cache.exists():
            recommendations_cache.unlink()
            print("Recommendations cache cleared")

    if args.clear_rejected:
        from interactive_filter import REJECTED_ARTISTS_FILE
        if REJECTED_ARTISTS_FILE.exists():
            REJECTED_ARTISTS_FILE.unlink()
            print("Rejected artists cleared")
        else:
            print("No rejected artists found")

    # Handle HTML regeneration only
    if args.regenerate_html:
        print("\nRegenerating HTML visualisation from cached recommendations...")
        recommendations = load_recommendations_cache(args.rarity)

        if recommendations is None:
            print("Error: No cached recommendations found.")
            print("Run without --regenerate-html to generate recommendations first.")
            sys.exit(1)

        library = get_library_parser()
        artist_stats = library.get_artist_stats()
        library_stats = library.get_library_stats()
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()

        HTML_VISUALISATION(recommendations, loved_artists, args.limit, None, library_stats)
        return

    # Try to load cached recommendations first
    recommendations = load_recommendations_cache(args.rarity)

    if recommendations is None:
        library = get_library_parser()
        artist_stats = library.get_artist_stats(force_refresh=args.scan_library)
        library_stats = library.get_library_stats()

        lastfm = LastFmClient(LASTFM_API_KEY)

        engine = RecommendationEngine(artist_stats, lastfm)
        recommendations = engine.generate_recommendations(
            rarity_pref=args.rarity,
            max_artist_listeners=MAX_ARTIST_LISTENERS
        )

        if not recommendations:
            print("\nNo recommendations found. Try:")
            print("- Ensuring you have loved/frequently played artists in your library")
            print("- Running with --refresh-cache to update metadata")
            return

        loved_artists = engine.get_loved_artists()
        save_recommendations_cache(recommendations, loved_artists, args.rarity)
    else:
        library = get_library_parser()
        artist_stats = library.get_artist_stats(force_refresh=args.scan_library)
        library_stats = library.get_library_stats()
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)

    # Filter out previously rejected artists
    recommendations = filter_rejected_from_recommendations(recommendations)

    if not recommendations:
        print("\nNo recommendations remaining after filtering rejected artists.")
        print("All recommendations have been previously rejected.")
        return

    # Show interactive filter if enabled (and not disabled via flag)
    if CLI_INTERACTIVE_FILTERING and not args.no_interactive:
        try:
            recommendations = show_interactive_filter(recommendations, args.limit)
            if not recommendations:
                print("\nNo recommendations selected. Exiting.")
                return
        except KeyboardInterrupt:
            print("\n\nInteractive filtering cancelled. Keeping all recommendations.")

    # Create Apple Music playlist if enabled
    artist_music_data = {}
    if CREATE_PLAYLIST:
        # Sort recommendations by primary genre tag for smoother playlist listening
        # Group by primary tag, then by score within each group
        sorted_for_playlist = sorted(
            recommendations[:args.limit],
            key=lambda x: (x.get('tags', ['unknown'])[0] if x.get('tags') else 'unknown', -x['score'])
        )

        # Log notice about songs per artist multiplier
        if PLAYLIST_SONGS_PER_ARTIST > 1:
            expected_songs = len(sorted_for_playlist) * PLAYLIST_SONGS_PER_ARTIST
            print(f"\nNote: PLAYLIST_SONGS_PER_ARTIST={PLAYLIST_SONGS_PER_ARTIST}")
            print(f"Playlist will contain approximately {len(sorted_for_playlist)} artists × {PLAYLIST_SONGS_PER_ARTIST} songs = ~{expected_songs} total songs\n")

        # Get Apple Music song data using Playwright scraper
        result = create_apple_music_playlist_with_scraping(
            sorted_for_playlist,
            args.limit,
            PLAYLIST_SONGS_PER_ARTIST,
            AM_SCRAPE_BATCH_SIZE
        )

        artist_music_data = result.get('artist_data', {})

        # Validate data - filter out any known artists
        validated_data = {}
        filtered_count = 0
        for artist_name, data in artist_music_data.items():
            if not engine._contains_known_artist(artist_name):
                validated_data[artist_name] = data
            else:
                filtered_count += 1
                print(f"  Filtered out '{artist_name}' - contains known artist from library")

        if filtered_count > 0:
            print(f"\n✓ Filtered {filtered_count} artist(s) that matched library artists")

        artist_music_data = validated_data

        # Create playlist using Web API
        playlist_id = create_beatfinder_playlist(validated_data, merge=PLAYLIST_MERGE_MODE, skip_library_check=PLAYLIST_SKIP_LIBRARY_CHECK)
        if not playlist_id:
            print("Note: Could not create Apple Music playlist (tokens may need refreshing)")

    # Output results
    output_file = Path("recommendations.md")
    markdown = format_recommendations(recommendations, args.limit, artist_music_data, library_stats)
    output_file.write_text(markdown)

    print(f"\n✓ Generated {min(len(recommendations), args.limit)} recommendations")
    print(f"✓ Saved to: {output_file}")

    # Show top 3
    print("\nTop 3 recommendations:")
    for i, rec in enumerate(recommendations[:3], 1):
        print(f"{i}. {rec['name']} (recommended by {rec['frequency']} artists)")

    # Generate HTML visualisation if enabled
    loved_artists = engine.get_loved_artists()
    HTML_VISUALISATION(recommendations, loved_artists, args.limit, artist_music_data, library_stats)

    # Save run to history file (for web UI)
    save_run_to_history(args.limit, args.rarity, len(recommendations))


if __name__ == "__main__":
    main()
