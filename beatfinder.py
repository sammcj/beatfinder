#!/usr/bin/env python3
"""
BeatFinder - Discover new artists based on your Apple Music library
"""

import argparse
import json
import os
import plistlib
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests
from dotenv import load_dotenv


# Configuration
load_dotenv()
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
MAX_RECOMMENDATIONS = int(os.getenv("MAX_RECOMMENDATIONS", "15"))

# Artist classification thresholds
KNOWN_ARTIST_MIN_PLAY_COUNT = int(os.getenv("KNOWN_ARTIST_MIN_PLAY_COUNT", "3"))
KNOWN_ARTIST_MIN_TRACKS = int(os.getenv("KNOWN_ARTIST_MIN_TRACKS", "5"))
LOVED_PLAY_COUNT_THRESHOLD = int(os.getenv("LOVED_PLAY_COUNT_THRESHOLD", "50"))
LOVED_MIN_TRACK_RATING = int(os.getenv("LOVED_MIN_TRACK_RATING", "4"))  # 1-5 stars
LOVED_MIN_ARTIST_PLAYS = int(os.getenv("LOVED_MIN_ARTIST_PLAYS", "10"))

# Cache settings
CACHE_EXPIRY_DAYS = int(os.getenv("CACHE_EXPIRY_DAYS", "7"))
RECOMMENDATIONS_CACHE_EXPIRY_DAYS = int(os.getenv("RECOMMENDATIONS_CACHE_EXPIRY_DAYS", "7"))

RARITY_PREFERENCE = int(os.getenv("RARITY_PREFERENCE", "7"))

# Validate rarity preference
if not 1 <= RARITY_PREFERENCE <= 10:
    print(f"Warning: RARITY_PREFERENCE={RARITY_PREFERENCE} is out of range (1-10). Using default: 7")
    RARITY_PREFERENCE = 7

# Performance settings
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
MAX_REQUESTS_PER_SECOND = int(os.getenv("MAX_REQUESTS_PER_SECOND", "5"))

# Advanced recommendation features
ENABLE_TAG_SIMILARITY = os.getenv("ENABLE_TAG_SIMILARITY", "false").lower() == "true"
ENABLE_PLAY_FREQUENCY_WEIGHTING = os.getenv("ENABLE_PLAY_FREQUENCY_WEIGHTING", "false").lower() == "true"
LAST_MONTHS_FILTER = int(os.getenv("LAST_MONTHS_FILTER", "0"))

# Tag ignore list - parse comma-separated tags and normalise to lowercase
TAG_IGNORE_LIST_RAW = os.getenv("TAG_IGNORE_LIST", "")
TAG_IGNORE_LIST = set(tag.strip().lower() for tag in TAG_IGNORE_LIST_RAW.split(",") if tag.strip())

# Apple Music playlist creation
CREATE_APPLE_MUSIC_PLAYLIST = os.getenv("CREATE_APPLE_MUSIC_PLAYLIST", "false").lower() == "true"
PLAYLIST_SONGS_PER_ARTIST = int(os.getenv("PLAYLIST_SONGS_PER_ARTIST", "3"))

# HTML visualisation
GENERATE_HTML_VISUALISATION = os.getenv("GENERATE_HTML_VISUALISATION", "false").lower() == "true"

# Scoring weights (when advanced features enabled)
SCORING_FREQUENCY_WEIGHT = float(os.getenv("SCORING_FREQUENCY_WEIGHT", "0.3"))
SCORING_TAG_OVERLAP_WEIGHT = float(os.getenv("SCORING_TAG_OVERLAP_WEIGHT", "0.3"))
SCORING_MATCH_WEIGHT = float(os.getenv("SCORING_MATCH_WEIGHT", "0.2"))
SCORING_RARITY_WEIGHT = float(os.getenv("SCORING_RARITY_WEIGHT", "0.2"))

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def show_config():
    """Display configuration settings"""
    print("\n" + "="*60)
    print("BeatFinder Configuration")
    print("="*60)
    print(f"Max recommendations: {MAX_RECOMMENDATIONS}")
    print(f"\nArtist classification:")
    print(f"  'Known' (filtered from recommendations):")
    print(f"    - {KNOWN_ARTIST_MIN_PLAY_COUNT}+ plays, OR")
    print(f"    - {KNOWN_ARTIST_MIN_TRACKS}+ tracks in library")
    print(f"  'Loved' (used for taste profile):")
    print(f"    - {LOVED_PLAY_COUNT_THRESHOLD}+ plays, OR")
    print(f"    - {LOVED_MIN_TRACK_RATING}+ star rating with {LOVED_MIN_ARTIST_PLAYS}+ plays")
    print(f"\nRarity preference: {RARITY_PREFERENCE}")
    print(f"Last.fm cache expiry: {CACHE_EXPIRY_DAYS} days")
    print(f"Recommendations cache expiry: {RECOMMENDATIONS_CACHE_EXPIRY_DAYS} days")

    # Show advanced features if enabled
    advanced_features = []
    if ENABLE_TAG_SIMILARITY:
        advanced_features.append("Tag similarity matching")
    if ENABLE_PLAY_FREQUENCY_WEIGHTING:
        advanced_features.append("Play frequency weighting")
    if LAST_MONTHS_FILTER > 0:
        advanced_features.append(f"Time filter: last {LAST_MONTHS_FILTER} months")
    if CREATE_APPLE_MUSIC_PLAYLIST:
        advanced_features.append(f"Create playlist ({PLAYLIST_SONGS_PER_ARTIST} songs per artist)")

    if advanced_features:
        print("\nAdvanced features enabled:")
        for feature in advanced_features:
            print(f"  • {feature}")

    # Show ignored tags if any
    if TAG_IGNORE_LIST:
        print(f"\nIgnored tags: {', '.join(sorted(TAG_IGNORE_LIST))}")

    print("="*60 + "\n")


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
            play_date_utc = track.get('Play Date UTC')

            artist_stats[artist]["play_count"] += play_count
            artist_stats[artist]["track_count"] += 1

            # Mark if any track is explicitly "loved" in Apple Music
            if loved:
                artist_stats[artist]["loved"] = True

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


class RateLimiter:
    """Thread-safe rate limiter to ensure we don't exceed API limits"""

    def __init__(self, max_per_second: int):
        self.max_per_second = max_per_second
        self.min_interval = 1.0 / max_per_second
        self.last_request_time = 0
        self.lock = threading.Lock()

    def acquire(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)

            self.last_request_time = time.time()


class LastFmClient:
    """Last.fm API client with caching"""

    BASE_URL = "http://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str):
        if not api_key or api_key == "your_api_key_here":
            print("\nError: Last.fm API key not configured!")
            print("\nPlease set up your API key:")
            print("1. Get a free API key at: https://www.last.fm/api/account/create")
            print("2. Copy .env.example to .env")
            print("3. Edit .env and add your API key to LASTFM_API_KEY")
            sys.exit(1)

        self.api_key = api_key
        self.session = requests.Session()
        self.cache_file = CACHE_DIR / "lastfm_cache.json"
        self.cache_lock = threading.Lock()  # Protect cache from concurrent access
        self.rate_limiter = RateLimiter(MAX_REQUESTS_PER_SECOND)  # Global rate limiter
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """Load cached API responses"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    # Check if cache is expired
                    cache_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
                    if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRY_DAYS):
                        return cache
            except Exception:
                pass
        return {"timestamp": datetime.now().isoformat(), "data": {}}

    def _save_cache(self):
        """Save cache to disk (thread-safe)"""
        with self.cache_lock:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)

    def _make_request(self, params: Dict) -> Dict:
        """Make API request with global rate limiting"""
        params["api_key"] = self.api_key
        params["format"] = "json"

        try:
            # Enforce global rate limit across all threads
            self.rate_limiter.acquire()
            response = self.session.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except json.JSONDecodeError as e:
            print(f"\nError: Failed to parse Last.fm API response as JSON")
            print(f"Response content: {response.text[:200]}")
            print(f"\nThis usually means your Last.fm API key is missing or invalid.")
            print(f"Please check your .env file and ensure LASTFM_API_KEY is set correctly.")
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            return {}

    def get_similar_artists(self, artist_name: str, limit: int = 20) -> List[Dict]:
        """
        Get similar artists from Last.fm (thread-safe)

        Returns list of dicts with keys: name, match, listeners, tags
        """
        cache_key = f"similar_{artist_name.lower()}"

        # Check cache with lock
        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        # Make API request outside lock
        params = {
            "method": "artist.getsimilar",
            "artist": artist_name,
            "limit": limit
        }

        data = self._make_request(params)
        similar = []

        if "similarartists" in data and "artist" in data["similarartists"]:
            for artist in data["similarartists"]["artist"]:
                similar.append({
                    "name": artist.get("name", ""),
                    "match": float(artist.get("match", 0)),
                    "listeners": int(artist.get("listeners", 0)) if "listeners" in artist else 0,
                })

        # Get tags for each similar artist
        for artist in similar:
            artist["tags"] = self.get_artist_tags(artist["name"])

        # Save to cache with lock
        with self.cache_lock:
            self.cache["data"][cache_key] = similar
        self._save_cache()

        return similar

    def get_artist_tags(self, artist_name: str, limit: int = 10) -> List[str]:
        """Get top tags for an artist (thread-safe)"""
        cache_key = f"tags_{artist_name.lower()}"

        # Check cache with lock
        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        # Make API request outside lock
        params = {
            "method": "artist.gettoptags",
            "artist": artist_name,
            "limit": limit
        }

        data = self._make_request(params)
        tags = []

        if "toptags" in data and "tag" in data["toptags"]:
            tags = [tag["name"] for tag in data["toptags"]["tag"] if "name" in tag]

        # Save to cache with lock
        with self.cache_lock:
            self.cache["data"][cache_key] = tags
        self._save_cache()

        return tags

    def get_artist_info(self, artist_name: str) -> Dict:
        """Get detailed artist information (thread-safe)"""
        cache_key = f"info_{artist_name.lower()}"

        # Check cache with lock
        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        # Make API request outside lock
        params = {
            "method": "artist.getinfo",
            "artist": artist_name
        }

        data = self._make_request(params)
        info = {}

        if "artist" in data:
            artist = data["artist"]
            info = {
                "listeners": int(artist.get("stats", {}).get("listeners", 0)),
                "playcount": int(artist.get("stats", {}).get("playcount", 0)),
                "tags": [tag["name"] for tag in artist.get("tags", {}).get("tag", [])[:10]]
            }

        # Save to cache with lock
        with self.cache_lock:
            self.cache["data"][cache_key] = info
        self._save_cache()

        return info


class RecommendationEngine:
    """Generate artist recommendations"""

    def __init__(self, library_stats: Dict, lastfm_client: LastFmClient):
        self.library_stats = library_stats
        self.lastfm = lastfm_client
        # Build set of "known" artists
        # An artist is "known" if they have either:
        # - Sufficient plays (shows listening history), OR
        # - Sufficient tracks in library (shows intentional collection, even for streaming)
        # Use normalised names for better matching (handles quotes, spacing variations)
        self.known_artists = set(
            self._normalise_artist_name(artist)
            for artist, stats in library_stats.items()
            if (stats["play_count"] >= KNOWN_ARTIST_MIN_PLAY_COUNT or
                stats["track_count"] >= KNOWN_ARTIST_MIN_TRACKS)
        )

    @staticmethod
    def _normalise_artist_name(name: str) -> str:
        """Normalise artist name for matching by removing punctuation variations"""
        normalised = name.lower()
        # Replace various quote styles with nothing
        normalised = normalised.replace('"', '').replace("'", '').replace(''', '').replace(''', '')
        # Collapse multiple spaces
        normalised = ' '.join(normalised.split())
        return normalised

    def get_loved_artists(self) -> List[str]:
        """Get list of loved or frequently played artists for building taste profile"""
        loved = []
        cutoff_date = None

        # Apply time filter if configured
        if LAST_MONTHS_FILTER > 0:
            cutoff_date = datetime.now() - timedelta(days=LAST_MONTHS_FILTER * 30)

        for artist, stats in self.library_stats.items():
            is_loved = False

            # Check if artist qualifies as "loved" for taste profile:
            # 1. Any track explicitly marked as "loved" in library
            if stats["loved"]:
                is_loved = True
            # 2. High play count threshold
            elif stats["play_count"] >= LOVED_PLAY_COUNT_THRESHOLD:
                is_loved = True
            # 3. High rating with minimum play requirement
            # Convert 1-5 star rating to 0-100 scale (stored in XML as rating * 20)
            elif stats["rating"] >= (LOVED_MIN_TRACK_RATING * 20) and stats["play_count"] >= LOVED_MIN_ARTIST_PLAYS:
                is_loved = True

            if is_loved:
                # Apply time filter if enabled
                if cutoff_date and stats.get("last_played"):
                    # Skip if last played before cutoff date
                    if stats["last_played"] < cutoff_date:
                        continue

                loved.append(artist)

        return loved

    def build_tag_profile(self, loved_artists: List[str]) -> Dict[str, float]:
        """Build a tag profile from loved artists for similarity matching (concurrent)"""
        if not ENABLE_TAG_SIMILARITY:
            return {}

        print("Building music taste profile from your loved artists...")

        tag_counts = defaultdict(float)
        total_tags = 0

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_tags(artist: str) -> tuple:
            """Fetch tags for one artist"""
            tags = self.lastfm.get_artist_tags(artist, limit=10)
            play_count = self.library_stats.get(artist, {}).get("play_count", 1)
            return artist, tags, play_count

        # Collect tags from all loved artists concurrently
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            futures = {executor.submit(fetch_tags, artist): artist for artist in loved_artists}

            completed = 0
            failed = 0

            for future in as_completed(futures):
                try:
                    artist, tags, play_count = future.result()
                    completed += 1

                    # Weight tags by play frequency if enabled
                    weight = play_count if ENABLE_PLAY_FREQUENCY_WEIGHTING else 1

                    for tag in tags:
                        tag_lower = tag.lower()
                        # Skip ignored tags
                        if tag_lower in TAG_IGNORE_LIST:
                            continue
                        tag_counts[tag_lower] += weight
                        total_tags += weight

                    # Show progress
                    if completed % 50 == 0 or completed == len(loved_artists):
                        status = f"  Progress: {completed}/{len(loved_artists)} artists analysed"
                        if failed > 0:
                            status += f" ({failed} failed)"
                        print(status + "...")

                except Exception:
                    failed += 1
                    continue

        # Normalise to probabilities
        tag_profile = {}
        for tag, count in tag_counts.items():
            tag_profile[tag] = count / total_tags if total_tags > 0 else 0

        # Show top tags
        top_tags = sorted(tag_profile.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"✓ Your top music tags: {', '.join([tag for tag, _ in top_tags])}\n")

        return tag_profile

    def calculate_tag_similarity(self, artist_tags: List[str], tag_profile: Dict[str, float]) -> float:
        """Calculate how well an artist's tags match the user's tag profile"""
        if not tag_profile or not artist_tags:
            return 0.0

        # Filter out ignored tags and calculate weighted overlap
        similarity = 0.0
        valid_tag_count = 0
        for tag in artist_tags:
            tag_lower = tag.lower()
            # Skip ignored tags
            if tag_lower in TAG_IGNORE_LIST:
                continue
            similarity += tag_profile.get(tag_lower, 0)
            valid_tag_count += 1

        # Normalise by number of valid (non-ignored) tags
        return similarity / valid_tag_count if valid_tag_count > 0 else 0.0

    def generate_recommendations(self, rarity_pref: str = "medium") -> List[Dict]:
        """
        Generate artist recommendations

        Args:
            rarity_pref: "low" (popular), "medium", or "high" (obscure)

        Returns:
            List of recommendation dicts with keys:
            - name: artist name
            - score: recommendation score
            - recommended_by: list of artists that led to this recommendation
            - listeners: Last.fm listener count
            - tags: genre tags
            - rarity_score: obscurity score
        """
        loved_artists = self.get_loved_artists()
        print(f"Analysing {len(loved_artists)} loved/frequently played artists...")

        # Build tag profile if tag similarity is enabled
        tag_profile = self.build_tag_profile(loved_artists)

        # Collect all similar artists using concurrent requests
        recommendations = defaultdict(lambda: {
            "recommended_by": [],
            "recommender_weights": [],  # Play counts of artists that recommend this
            "listeners": 0,
            "tags": set(),
            "match_scores": []
        })

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_similar(artist: str) -> tuple:
            """Fetch similar artists for one artist"""
            similar = self.lastfm.get_similar_artists(artist)
            return artist, similar

        # Process artists concurrently to respect rate limits
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            futures = {executor.submit(fetch_similar, artist): artist for artist in loved_artists}

            completed = 0
            failed = 0
            for future in as_completed(futures):
                try:
                    artist, similar = future.result()
                    completed += 1

                    if completed % 50 == 0 or completed == len(loved_artists):
                        status = f"  Progress: {completed}/{len(loved_artists)} artists processed"
                        if failed > 0:
                            status += f" ({failed} failed)"
                        print(status + "...")

                    for sim_artist in similar:
                        name = sim_artist["name"]

                        # Skip if artist is "known" (in library with sufficient plays or tracks)
                        # Check both exact name and normalised name for spelling variations
                        if self._normalise_artist_name(name) in self.known_artists:
                            continue

                        # Also check exact name match (catches case variations)
                        if name in self.library_stats:
                            stats = self.library_stats[name]
                            if (stats["play_count"] >= KNOWN_ARTIST_MIN_PLAY_COUNT or
                                stats["track_count"] >= KNOWN_ARTIST_MIN_TRACKS):
                                continue

                        recommendations[name]["recommended_by"].append(artist)
                        recommendations[name]["match_scores"].append(sim_artist["match"])
                        recommendations[name]["listeners"] = sim_artist.get("listeners", 0)
                        recommendations[name]["tags"].update(sim_artist.get("tags", []))

                        # Track play count of recommending artist for weighting
                        if ENABLE_PLAY_FREQUENCY_WEIGHTING:
                            recommender_play_count = self.library_stats.get(artist, {}).get("play_count", 1)
                            recommendations[name]["recommender_weights"].append(recommender_play_count)
                except Exception as e:
                    failed += 1
                    # Skip this artist and continue with others
                    continue

        print(f"\nFound {len(recommendations)} potential recommendations")

        # Score and rank recommendations
        scored_recommendations = []
        for name, data in recommendations.items():
            # Base frequency score
            frequency_score = len(data["recommended_by"])

            # Apply play frequency weighting if enabled
            if ENABLE_PLAY_FREQUENCY_WEIGHTING and data["recommender_weights"]:
                # Weight by play counts of recommending artists
                weighted_frequency = sum(data["recommender_weights"]) / len(data["recommender_weights"])
                # Normalise (assuming max play count of 1000)
                frequency_score = weighted_frequency / 100

            avg_match = sum(data["match_scores"]) / len(data["match_scores"])

            # Rarity score (inverse of popularity)
            listeners = data["listeners"] or 1
            rarity_score = 1 / (1 + listeners / 1000000)  # Normalised

            # Tag similarity score
            tag_similarity = 0.0
            if ENABLE_TAG_SIMILARITY and tag_profile:
                tag_similarity = self.calculate_tag_similarity(list(data["tags"]), tag_profile)

            # Combined score
            if ENABLE_TAG_SIMILARITY or ENABLE_PLAY_FREQUENCY_WEIGHTING:
                # Use configurable weights
                score = (
                    (frequency_score * SCORING_FREQUENCY_WEIGHT) +
                    (tag_similarity * SCORING_TAG_OVERLAP_WEIGHT) +
                    (avg_match * SCORING_MATCH_WEIGHT) +
                    (rarity_score * SCORING_RARITY_WEIGHT)
                )
            else:
                # Use rarity preference scoring (1-10 scale)
                # Calculate weights based on preference: 1=popular, 10=obscure
                rarity_weight = 0.1 + (rarity_pref - 1) * 0.3 / 9  # 0.1 to 0.4
                frequency_weight = 0.5 - (rarity_pref - 1) * 0.1 / 9  # 0.5 to 0.4
                match_weight = 1.0 - rarity_weight - frequency_weight  # Remainder
                score = (frequency_score * frequency_weight) + (avg_match * match_weight) + (rarity_score * rarity_weight)

            scored_recommendations.append({
                "name": name,
                "score": score,
                "frequency": len(data["recommended_by"]),  # Store original count
                "avg_match": avg_match,
                "recommended_by": data["recommended_by"],
                "listeners": listeners,
                "tags": list(data["tags"])[:10],
                "rarity_score": rarity_score,
                "tag_similarity": tag_similarity,
                "rarity_pref": rarity_pref  # Store for recalculation
            })

        # Sort by score (initial scoring with potentially incomplete listener data)
        scored_recommendations.sort(key=lambda x: x["score"], reverse=True)

        # Fetch accurate listener counts for top recommendations
        print(f"Fetching detailed info for top {min(100, len(scored_recommendations))} recommendations...")
        for rec in scored_recommendations[:100]:  # Only fetch for top 100
            artist_info = self.lastfm.get_artist_info(rec["name"])
            if artist_info and artist_info.get("listeners", 0) > 0:
                rec["listeners"] = artist_info["listeners"]
                # Recalculate rarity score with accurate listener count
                rec["rarity_score"] = 1 / (1 + rec["listeners"] / 1000000)

                # Recalculate full score with updated rarity
                if ENABLE_TAG_SIMILARITY or ENABLE_PLAY_FREQUENCY_WEIGHTING:
                    # Use configurable weights
                    # Note: frequency_score needs to be recalculated if using play frequency weighting
                    freq_score = rec["frequency"]
                    rec["score"] = (
                        (freq_score * SCORING_FREQUENCY_WEIGHT) +
                        (rec["tag_similarity"] * SCORING_TAG_OVERLAP_WEIGHT) +
                        (rec["avg_match"] * SCORING_MATCH_WEIGHT) +
                        (rec["rarity_score"] * SCORING_RARITY_WEIGHT)
                    )
                else:
                    # Use rarity preference scoring (1-10 scale)
                    pref = rec["rarity_pref"]
                    rarity_weight = 0.1 + (pref - 1) * 0.3 / 9
                    frequency_weight = 0.5 - (pref - 1) * 0.1 / 9
                    match_weight = 1.0 - rarity_weight - frequency_weight
                    rec["score"] = (rec["frequency"] * frequency_weight) + (rec["avg_match"] * match_weight) + (rec["rarity_score"] * rarity_weight)

        # Re-sort with updated scores
        scored_recommendations.sort(key=lambda x: x["score"], reverse=True)

        return scored_recommendations


def save_recommendations_cache(recommendations: List[Dict], loved_artists: List[str], rarity_pref: int) -> None:
    """Save recommendations to cache with metadata"""
    cache_file = CACHE_DIR / "recommendations_cache.json"
    cache_data = {
        "timestamp": datetime.now().isoformat(),
        "rarity_preference": rarity_pref,
        "loved_artists_count": len(loved_artists),
        "recommendations": recommendations
    }

    with open(cache_file, 'w') as f:
        json.dump(cache_data, f, indent=2)

    print(f"✓ Cached {len(recommendations)} recommendations")


def load_recommendations_cache(rarity_pref: int) -> List[Dict] | None:
    """Load recommendations from cache if valid (not expired and matching rarity preference)"""
    cache_file = CACHE_DIR / "recommendations_cache.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)

        # Check cache age
        cache_time = datetime.fromisoformat(cache_data["timestamp"])
        age_days = (datetime.now() - cache_time).days

        if age_days > RECOMMENDATIONS_CACHE_EXPIRY_DAYS:
            print(f"Recommendations cache expired ({age_days} days old, limit: {RECOMMENDATIONS_CACHE_EXPIRY_DAYS} days)")
            return None

        # Check if rarity preference matches
        if cache_data.get("rarity_preference") != rarity_pref:
            print(f"Recommendations cache invalid (rarity preference changed: {cache_data.get('rarity_preference')} → {rarity_pref})")
            return None

        recommendations = cache_data["recommendations"]
        print(f"✓ Loaded {len(recommendations)} recommendations from cache ({age_days} days old)")
        return recommendations

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Warning: Failed to load recommendations cache: {e}")
        return None


def format_recommendations(recommendations: List[Dict], limit: int) -> str:
    """Format recommendations as markdown"""
    output = ["# BeatFinder Recommendations\n"]
    output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    output.append(f"Total recommendations: {len(recommendations)}\n")
    output.append("---\n")

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
            output.append(f"\n**Tags:** {', '.join(rec['tags'][:8])}\n")

        # Apple Music search link
        search_url = f"music://music.apple.com/search?term={rec['name'].replace(' ', '+')}"
        output.append(f"\n[Search in Apple Music]({search_url})\n")
        output.append("\n---\n")

    return "".join(output)


def create_apple_music_playlist(recommendations: List[Dict], limit: int) -> bool:
    """
    Create an Apple Music playlist with top songs from recommended artists

    Args:
        recommendations: List of recommendation dicts
        limit: Number of artists to include

    Returns:
        True if successful, False otherwise
    """
    if not CREATE_APPLE_MUSIC_PLAYLIST:
        return False

    playlist_name = f"BeatFinder Discoveries {datetime.now().strftime('%Y-%m-%d')}"
    print(f"\nCreating Apple Music playlist: '{playlist_name}'")
    print(f"Adding top {PLAYLIST_SONGS_PER_ARTIST} songs from each of {limit} artists...\n")

    # Check if playlist already exists and delete it (allows regenerating on same day)
    check_and_delete_script = f'''
    tell application "Music"
        set playlistExists to false
        try
            set existingPlaylist to playlist "{playlist_name}"
            delete existingPlaylist
            set playlistExists to true
        end try
        return playlistExists
    end tell
    '''

    try:
        result = subprocess.run(
            ['osascript', '-e', check_and_delete_script],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip() == "true":
            print(f"✓ Deleted existing playlist: '{playlist_name}'")
    except Exception:
        pass  # Playlist didn't exist, continue

    # Create playlist via AppleScript
    create_playlist_script = f'''
    tell application "Music"
        set newPlaylist to make new playlist with properties {{name:"{playlist_name}"}}
        return newPlaylist's name
    end tell
    '''

    try:
        result = subprocess.run(
            ['osascript', '-e', create_playlist_script],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"Error creating playlist: {result.stderr}")
            return False

        print(f"✓ Created playlist: {playlist_name}")

        # Add songs for each recommended artist
        added_count = 0
        failed_artists = []

        for idx, rec in enumerate(recommendations[:limit], 1):
            artist_name = rec['name']
            # Escape quotes in artist name for AppleScript
            escaped_artist = artist_name.replace('"', '\\"').replace("'", "\\'")

            print(f"  [{idx}/{limit}] Searching for {artist_name}...", end=" ")

            # Search for artist and add their top songs
            add_songs_script = f'''
            tell application "Music"
                set searchResults to search playlist "Library" for "{escaped_artist}"
                set artistTracks to {{}}

                -- Find tracks by this artist
                repeat with aTrack in searchResults
                    try
                        if artist of aTrack is "{escaped_artist}" then
                            set end of artistTracks to aTrack
                        end if
                    end try
                end repeat

                -- Sort by play count and add top songs
                set addedCount to 0
                set maxSongs to {PLAYLIST_SONGS_PER_ARTIST}

                repeat with aTrack in artistTracks
                    if addedCount >= maxSongs then exit repeat
                    try
                        duplicate aTrack to playlist "{playlist_name}"
                        set addedCount to addedCount + 1
                    end try
                end repeat

                return addedCount
            end tell
            '''

            try:
                result = subprocess.run(
                    ['osascript', '-e', add_songs_script],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0 and result.stdout.strip().isdigit():
                    songs_added = int(result.stdout.strip())
                    if songs_added > 0:
                        print(f"✓ Added {songs_added} songs")
                        added_count += songs_added
                    else:
                        print("✗ No songs found")
                        failed_artists.append(artist_name)
                else:
                    print(f"✗ Error")
                    failed_artists.append(artist_name)

            except subprocess.TimeoutExpired:
                print("✗ Timeout")
                failed_artists.append(artist_name)
            except Exception as e:
                print(f"✗ {str(e)}")
                failed_artists.append(artist_name)

        # Summary
        print(f"\n✓ Playlist created with {added_count} songs from {limit - len(failed_artists)}/{limit} artists")

        if failed_artists:
            print(f"\nCouldn't find songs for {len(failed_artists)} artists:")
            for artist in failed_artists[:5]:
                print(f"  - {artist}")
            if len(failed_artists) > 5:
                print(f"  - ...and {len(failed_artists) - 5} more")

        print(f"\nOpen Music.app to find your playlist: '{playlist_name}'")
        return True

    except Exception as e:
        print(f"Error creating playlist: {e}")
        return False


def generate_html_visualisation(recommendations: List[Dict], loved_artists: List[str], limit: int) -> bool:
    """
    Generate an interactive HTML visualisation showing recommendation connections

    Args:
        recommendations: List of recommendation dicts
        loved_artists: List of loved artist names
        limit: Number of recommendations to include

    Returns:
        True if successful, False otherwise
    """
    if not GENERATE_HTML_VISUALISATION:
        return False

    output_file = Path("recommendations_visualisation.html")
    print(f"\nGenerating HTML visualisation: '{output_file.name}'...")

    # Prepare data for visualisation
    nodes = []
    edges = []
    node_ids = {}
    node_id_counter = 0

    # First pass: determine which loved artists will actually have visible edges
    # (limit to first 3 recommenders per green node)
    artists_with_edges = set()
    for rec in recommendations[:limit]:
        visible_recommenders = [r for r in rec["recommended_by"] if r in loved_artists]
        # Only count first 3 as having edges
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
                "value": 8,  # Smaller size for loved artists
                "font": {"bold": False}  # Normal font weight
            })
            node_id_counter += 1

    # Add recommended artists as nodes and create edges
    for idx, rec in enumerate(recommendations[:limit], 1):
        artist_name = rec["name"]
        node_ids[artist_name] = node_id_counter

        # Get visible recommenders (those that are in the graph)
        visible_recommenders = [r for r in rec["recommended_by"] if r in node_ids]
        total_in_library = len([r for r in rec["recommended_by"] if r in loved_artists])
        show_count = min(3, len(visible_recommenders))

        # Create tooltip with metadata
        tooltip_extra = f" (+{total_in_library - 3} more, click for details)" if total_in_library > 3 else ""
        tooltip = f"""
        <b>{artist_name}</b><br>
        Score: {rec['score']:.2f}<br>
        Listeners: {rec['listeners']:,}<br>
        Recommended by: {rec['frequency']} artists{tooltip_extra}<br>
        Tags: {', '.join(rec['tags'][:5])}
        """

        # Add visual indicator to label if more than 3 recommenders
        label_extra = f"\n(+{total_in_library - 3} more)" if total_in_library > 3 else ""
        node_label = f"{artist_name}{label_extra}"

        nodes.append({
            "id": node_id_counter,
            "label": node_label,
            "group": "recommended",
            "title": tooltip.strip(),
            "value": rec['score'] * 15,  # Make green nodes larger (increased from 10)
            "font": {"bold": True},  # Bold text for recommendations
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

        # Create edges from recommenders (limit to first 3 for performance)
        for recommender in visible_recommenders[:show_count]:
            edges.append({
                "from": node_ids[recommender],
                "to": node_id_counter,
                "title": f"{recommender} → {artist_name}"
            })

        node_id_counter += 1

    # Build table rows HTML
    table_rows_html = ""
    for idx, rec in enumerate(recommendations[:limit], 1):
        artist_name = rec["name"]
        score = rec["score"]
        listeners = rec["listeners"]
        rarity = rec["rarity_score"]
        frequency = rec["frequency"]
        tags = rec.get("tags", [])[:5]  # Top 5 tags
        recommenders = rec["recommended_by"][:5]  # Top 5 recommenders

        # Apple Music search link
        search_url = f"music://music.apple.com/search?term={artist_name.replace(' ', '+')}"

        # Format tags
        tags_html = " ".join([f'<span class="tag">{tag}</span>' for tag in tags])

        # Format recommenders
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
                    <td><a href="{search_url}" class="link">🎵 Search</a></td>
                </tr>"""

    # Generate HTML with embedded vis.js
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>BeatFinder Recommendations VISUALISATION</title>
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
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        th {{
            background: #4a90e2;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .rank {{
            font-weight: bold;
            color: #4a90e2;
            font-size: 18px;
        }}
        .score {{
            font-weight: 600;
            color: #7bc043;
        }}
        .tags {{
            color: #666;
            font-size: 13px;
        }}
        .tag {{
            display: inline-block;
            background: #e8f5e8;
            padding: 2px 8px;
            border-radius: 12px;
            margin: 2px;
        }}
        .recommenders {{
            font-size: 13px;
            color: #666;
        }}
        .link {{
            color: #4a90e2;
            text-decoration: none;
        }}
        .link:hover {{
            text-decoration: underline;
        }}
        .footer {{
            text-align: center;
            padding: 40px 20px 20px;
            color: #999;
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
            animation: fadeIn 0.2s;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        .modal-content {{
            background-color: white;
            margin: 10% auto;
            padding: 30px;
            border-radius: 12px;
            width: 90%;
            max-width: 600px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            position: relative;
            animation: slideIn 0.3s;
        }}
        @keyframes slideIn {{
            from {{ transform: translateY(-50px); opacity: 0; }}
            to {{ transform: translateY(0); opacity: 1; }}
        }}
        .modal-close {{
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            line-height: 20px;
        }}
        .modal-close:hover {{
            color: #000;
        }}
        .modal-header {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .modal-title {{
            margin: 0;
            color: #333;
            font-size: 24px;
        }}
        .modal-subtitle {{
            color: #666;
            font-size: 14px;
            margin-top: 5px;
        }}
        .modal-section {{
            margin: 15px 0;
        }}
        .modal-section-title {{
            font-weight: 600;
            color: #4a90e2;
            margin-bottom: 8px;
        }}
        .modal-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 8px;
        }}
        .modal-tag {{
            background: #e8f5e8;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
        }}
        .modal-list {{
            list-style: none;
            padding: 0;
            margin: 8px 0;
        }}
        .modal-list li {{
            padding: 4px 0;
            color: #666;
        }}
        .modal-button {{
            display: inline-block;
            background: #4a90e2;
            color: white;
            padding: 10px 20px;
            border-radius: 6px;
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
        <p class="info-title">BeatFinder Recommendations</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <p><strong>Showing:</strong> {len([n for n in nodes if n['group'] == 'loved'])} loved artists → {limit} recommended artists</p>
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color loved"></div>
                <span>Your Loved Artists</span>
            </div>
            <div class="legend-item">
                <div class="legend-color recommended"></div>
                <span>Recommended Artists (size = score)</span>
            </div>
        </div>
        <p style="color: #666; font-size: 14px;">
            💡 <strong>Tips:</strong> Drag to pan • Scroll to zoom • Hover for details • Click nodes for more info
        </p>
    </div>
    <div id="network"></div>

    <!-- Modal for artist details -->
    <div id="artistModal" class="modal">
        <div class="modal-content">
            <span class="modal-close">&times;</span>
            <div id="modalBody"></div>
        </div>
    </div>

    <div class="recommendations-table">
        <h2>Recommended Artists</h2>
        <table>
            <thead>
                <tr>
                    <th style="width: 50px;">#</th>
                    <th>Artist</th>
                    <th style="width: 100px;">Score</th>
                    <th style="width: 120px;">Listeners</th>
                    <th style="width: 80px;">Rarity</th>
                    <th>Recommended By</th>
                    <th>Tags</th>
                    <th style="width: 80px;">Link</th>
                </tr>
            </thead>
            <tbody>
{table_rows_html}
            </tbody>
        </table>
    </div>

    <script>
        // Create network data
        const nodes = new vis.DataSet({json.dumps(nodes)});
        const edges = new vis.DataSet({json.dumps(edges)});

        // Network options
        const options = {{
            nodes: {{
                shape: 'dot',
                font: {{
                    size: 14,
                    face: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                }},
                borderWidth: 2,
                borderWidthSelected: 4
            }},
            edges: {{
                width: 1,
                color: {{
                    color: '#cccccc',
                    highlight: '#4a90e2',
                    hover: '#4a90e2'
                }},
                smooth: {{
                    type: 'continuous'
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
                        border: '#2c5f8d',
                        highlight: {{
                            background: '#5da3ff',
                            border: '#2c5f8d'
                        }}
                    }}
                }},
                recommended: {{
                    color: {{
                        background: '#7bc043',
                        border: '#5a8f32',
                        highlight: {{
                            background: '#93d65b',
                            border: '#5a8f32'
                        }}
                    }}
                }}
            }},
            physics: {{
                barnesHut: {{
                    gravitationalConstant: -8000,
                    centralGravity: 0.3,
                    springLength: 150,
                    springConstant: 0.04,
                    damping: 0.09
                }},
                stabilization: {{
                    iterations: 200
                }}
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 100,
                navigationButtons: true,
                keyboard: true
            }}
        }};

        // Create network
        const container = document.getElementById('network');
        const data = {{ nodes: nodes, edges: edges }};
        const network = new vis.Network(container, data, options);

        // Fit network to view when stabilized
        network.once('stabilizationIterationsDone', function() {{
            network.fit();
        }});

        // Handle node clicks to show modal
        const modal = document.getElementById('artistModal');
        const modalBody = document.getElementById('modalBody');
        const closeBtn = document.querySelector('.modal-close');

        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                const nodeId = params.nodes[0];
                const node = nodes.get(nodeId);

                let modalContent = '';

                if (node.group === 'loved') {{
                    // Show info for loved artist
                    const searchUrl = `music://music.apple.com/search?term=${{encodeURIComponent(node.label)}}`;
                    modalContent = `
                        <div class="modal-header">
                            <h2 class="modal-title">${{node.label}}</h2>
                            <div class="modal-subtitle">Your Loved Artist</div>
                        </div>
                        <div class="modal-section">
                            <div class="modal-section-title">About</div>
                            <p>This artist is in your loved artists collection and contributed to these recommendations.</p>
                        </div>
                        <a href="${{searchUrl}}" class="modal-button">🎵 Search in Apple Music</a>
                    `;
                }} else if (node.group === 'recommended') {{
                    // Show info for recommended artist
                    const data = node.data;
                    const searchUrl = `music://music.apple.com/search?term=${{encodeURIComponent(node.label)}}`;

                    const tagsHtml = data.tags.map(tag => `<span class="modal-tag">${{tag}}</span>`).join('');
                    const recommendersHtml = data.recommended_by.map(r => `<li>${{r}}</li>`).join('');

                    modalContent = `
                        <div class="modal-header">
                            <h2 class="modal-title">${{node.label}}</h2>
                            <div class="modal-subtitle">Recommended Artist</div>
                        </div>
                        <div class="modal-section">
                            <div class="modal-section-title">Recommendation Score</div>
                            <p style="font-size: 20px; font-weight: bold; color: #7bc043;">${{data.score.toFixed(3)}}</p>
                        </div>
                        <div class="modal-section">
                            <div class="modal-section-title">Stats</div>
                            <p><strong>Listeners:</strong> ${{data.listeners.toLocaleString()}}</p>
                            <p><strong>Rarity Score:</strong> ${{data.rarity.toFixed(3)}}</p>
                            <p><strong>Recommended by:</strong> ${{data.frequency}} of your artists</p>
                        </div>
                        <div class="modal-section">
                            <div class="modal-section-title">Recommended By</div>
                            <ul class="modal-list">
                                ${{recommendersHtml}}
                                ${{data.recommended_by.length > 10 ? '<li>...and more</li>' : ''}}
                            </ul>
                        </div>
                        <div class="modal-section">
                            <div class="modal-section-title">Tags</div>
                            <div class="modal-tags">
                                ${{tagsHtml}}
                            </div>
                        </div>
                        <a href="${{searchUrl}}" class="modal-button">🎵 Search in Apple Music</a>
                    `;
                }}

                modalBody.innerHTML = modalContent;
                modal.style.display = 'block';
            }}
        }});

        // Close modal when clicking X or outside
        closeBtn.onclick = function() {{
            modal.style.display = 'none';
        }};

        window.onclick = function(event) {{
            if (event.target === modal) {{
                modal.style.display = 'none';
            }}
        }};

        // Close on Escape key
        document.addEventListener('keydown', function(event) {{
            if (event.key === 'Escape' && modal.style.display === 'block') {{
                modal.style.display = 'none';
            }}
        }});
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


def main():
    parser = argparse.ArgumentParser(description="Discover new artists based on your Apple Music library")
    parser.add_argument("--scan-library", action="store_true", help="Force re-scan of Music library (slow)")
    parser.add_argument("--refresh-cache", action="store_true", help="Refresh Last.fm metadata cache (keeps recommendations cache)")
    parser.add_argument("--refresh-recommendations", action="store_true", help="Regenerate recommendations (keeps Last.fm cache)")
    parser.add_argument("--refresh-all", action="store_true", help="Clear all caches (Last.fm + recommendations)")
    parser.add_argument("--regenerate-html", action="store_true", help="Regenerate HTML visualisation from cached recommendations")
    parser.add_argument("--limit", type=int, default=MAX_RECOMMENDATIONS, help="Number of recommendations")
    parser.add_argument("--rarity", type=int, choices=range(1, 11), default=RARITY_PREFERENCE,
                       help="Rarity preference: 1 (most popular) to 10 (most obscure), default: 7")
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

    # Handle HTML regeneration only
    if args.regenerate_html:
        print("\nRegenerating HTML visualisation from cached recommendations...")
        recommendations = load_recommendations_cache(args.rarity)

        if recommendations is None:
            print("Error: No cached recommendations found.")
            print("Run without --regenerate-html to generate recommendations first.")
            sys.exit(1)

        # Load library to get loved artists
        library = AppleMusicLibrary()
        artist_stats = library.get_artist_stats()
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()

        # Generate HTML and exit
        generate_html_visualisation(recommendations, loved_artists, args.limit)
        return

    # Try to load cached recommendations first
    recommendations = load_recommendations_cache(args.rarity)

    if recommendations is None:
        # No valid cache, generate new recommendations
        # Extract library
        library = AppleMusicLibrary()
        artist_stats = library.get_artist_stats(force_refresh=args.scan_library)

        # Initialise Last.fm client
        lastfm = LastFmClient(LASTFM_API_KEY)

        # Generate recommendations
        engine = RecommendationEngine(artist_stats, lastfm)
        recommendations = engine.generate_recommendations(rarity_pref=args.rarity)

        if not recommendations:
            print("\nNo recommendations found. Try:")
            print("- Ensuring you have loved/frequently played artists in your library")
            print("- Running with --refresh-cache to update metadata")
            return

        # Cache the recommendations
        loved_artists = engine.get_loved_artists()
        save_recommendations_cache(recommendations, loved_artists, args.rarity)
    else:
        # Using cached recommendations, still need engine for visualisation
        library = AppleMusicLibrary()
        artist_stats = library.get_artist_stats(force_refresh=args.scan_library)
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)

    # Output results
    output_file = Path("recommendations.md")
    markdown = format_recommendations(recommendations, args.limit)
    output_file.write_text(markdown)

    print(f"\n✓ Generated {min(len(recommendations), args.limit)} recommendations")
    print(f"✓ Saved to: {output_file}")

    # Show top 3
    print("\nTop 3 recommendations:")
    for i, rec in enumerate(recommendations[:3], 1):
        print(f"{i}. {rec['name']} (recommended by {rec['frequency']} artists)")

    # Create Apple Music playlist if enabled
    create_apple_music_playlist(recommendations, args.limit)

    # Generate HTML visualisation if enabled
    loved_artists = engine.get_loved_artists()
    generate_html_visualisation(recommendations, loved_artists, args.limit)


if __name__ == "__main__":
    main()
