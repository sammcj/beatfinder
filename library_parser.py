#!/usr/bin/env python3
"""
Apple Music library parsing and caching
"""

import json
import plistlib
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

from config import CACHE_DIR, CACHE_EXPIRY_DAYS


class AppleMusicLibrary:
    """Extract artist data from Apple Music library XML export"""

    def __init__(self, xml_path: str = None):
        self.cache_file = CACHE_DIR / "library_cache.json"
        self.xml_path = Path(xml_path) if xml_path else self._find_library_xml()

    def _find_library_xml(self) -> Path:
        """Find Library.xml in common locations"""
        # Check Downloads folder first (where user exported it)
        downloads_xml = Path.home() / "Downloads" / "Library.xml"
        if downloads_xml.exists():
            return downloads_xml

        # Check default Music library location
        music_xml = Path.home() / "Music" / "Music" / "Library.xml"
        if music_xml.exists():
            return music_xml

        # Not found
        print("Error: Could not find Library.xml")
        print("\nPlease export your Apple Music library:")
        print("1. Open Music.app")
        print("2. File → Library → Export Library...")
        print("3. Save as 'Library.xml' to your Downloads folder")
        print("4. Run this script again")
        sys.exit(1)

    def _load_cached_stats(self) -> Dict:
        """Load cached library statistics"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    cache_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
                    if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRY_DAYS):
                        artists = cache.get("artists", {})
                        # Convert ISO strings back to datetime objects
                        for artist_data in artists.values():
                            if artist_data.get("last_played"):
                                artist_data["last_played"] = datetime.fromisoformat(artist_data["last_played"])
                        return artists
            except Exception:
                pass
        return {}

    def _save_cached_stats(self, stats: Dict):
        """Save library statistics to cache"""
        # Convert datetime objects to ISO strings for JSON serialisation
        serialisable_stats = {}
        for artist, data in stats.items():
            serialisable_stats[artist] = data.copy()
            if data.get("last_played"):
                serialisable_stats[artist]["last_played"] = data["last_played"].isoformat()

        cache = {
            "timestamp": datetime.now().isoformat(),
            "artists": serialisable_stats
        }
        with open(self.cache_file, 'w') as f:
            json.dump(cache, f, indent=2)

    def _parse_library_xml(self) -> Dict[str, Dict]:
        """Parse Library.xml and extract artist statistics"""
        print(f"Parsing library XML: {self.xml_path}")
        print(f"File size: {self.xml_path.stat().st_size / 1024 / 1024:.1f} MB")

        # Parse XML
        start_time = time.time()
        with open(self.xml_path, 'rb') as f:
            library = plistlib.load(f)

        parse_time = time.time() - start_time
        print(f"✓ Parsed in {parse_time:.1f} seconds")

        tracks = library.get('Tracks', {})
        print(f"Processing {len(tracks):,} tracks...")

        # Aggregate by artist
        artist_stats = defaultdict(lambda: {
            "play_count": 0,
            "loved": False,
            "disliked": False,
            "disliked_track_count": 0,
            "loved_track_count": 0,
            "rating": 0,
            "track_count": 0,
            "last_played": None
        })

        processed = 0
        for track_id, track in tracks.items():
            artist = track.get('Artist')
            if not artist:
                continue

            # Aggregate stats
            play_count = track.get('Play Count', 0)
            rating = track.get('Rating', 0)
            loved = track.get('Loved', False)
            disliked = track.get('Disliked', False)
            play_date_utc = track.get('Play Date UTC')

            artist_stats[artist]["play_count"] += play_count
            artist_stats[artist]["track_count"] += 1

            # Mark if any track is explicitly "loved" in Apple Music
            if loved:
                artist_stats[artist]["loved"] = True
                artist_stats[artist]["loved_track_count"] += 1

            # Mark if any track is explicitly "disliked" in Apple Music
            if disliked:
                artist_stats[artist]["disliked"] = True
                artist_stats[artist]["disliked_track_count"] += 1

            # Track the highest rating across all tracks for this artist
            artist_stats[artist]["rating"] = max(
                artist_stats[artist]["rating"],
                rating
            )

            # Track most recent play date
            if play_date_utc:
                if artist_stats[artist]["last_played"] is None:
                    artist_stats[artist]["last_played"] = play_date_utc
                elif play_date_utc > artist_stats[artist]["last_played"]:
                    artist_stats[artist]["last_played"] = play_date_utc

            processed += 1
            if processed % 10000 == 0:
                print(f"  Processed {processed:,} / {len(tracks):,} tracks...")

        print(f"✓ Found {len(artist_stats)} artists")
        return dict(artist_stats)

    def get_artist_stats(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Extract artist statistics from library

        Args:
            force_refresh: If True, ignore cache and scan library

        Returns:
            Dict with artist names as keys and stats as values:
            {
                "Artist Name": {
                    "play_count": int,
                    "loved": bool,
                    "disliked": bool,
                    "disliked_track_count": int,
                    "loved_track_count": int,
                    "rating": int,
                    "track_count": int
                }
            }
        """
        # Check cache first
        if not force_refresh:
            cached = self._load_cached_stats()
            if cached:
                print(f"Using cached library data ({len(cached)} artists)")
                print("Use --scan-library to force a fresh scan")
                return cached

        # Parse XML library export
        stats_dict = self._parse_library_xml()

        # Cache the results
        self._save_cached_stats(stats_dict)
        print("✓ Library data cached for future runs")

        return stats_dict

    def get_library_stats(self) -> Dict:
        """
        Get library statistics

        Note: iTunes Library XML doesn't provide rich statistics like Apple Music export.
        Returns empty dict for API compatibility with AppleMusicExportParser.

        Returns:
            Empty dict (iTunes XML doesn't include play history dates)
        """
        return {}
