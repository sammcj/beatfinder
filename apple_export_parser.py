#!/usr/bin/env python3
"""
Apple Music export data parser with efficient caching and checkpoint/resume support
"""

import json
import pickle
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

import pandas as pd

from config import CACHE_DIR, CACHE_EXPIRY_DAYS


class AppleMusicExportParser:
    """Parse Apple Music export data (streaming history + preferences)"""

    def __init__(self, export_dir: Path):
        """
        Initialise parser for Apple Music export directory

        Args:
            export_dir: Path to "Apple Music Activity" folder from Apple export
        """
        self.export_dir = Path(export_dir)
        self.cache_dir = CACHE_DIR / "apple_export"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache files
        self.stats_cache_file = self.cache_dir / "artist_stats.json"
        self.favorites_pickle = self.cache_dir / "favorites.pkl"
        self.play_activity_pickle = self.cache_dir / "play_activity.pkl"

        # Library statistics (populated when parsing)
        self.library_stats = {}

        # Validate export directory
        self._validate_export_dir()

    def _validate_export_dir(self):
        """Validate that export directory contains required files"""
        if not self.export_dir.exists():
            print(f"\nError: Apple Music export directory not found: {self.export_dir}")
            print("\nPlease download your Apple Music data:")
            print("1. Go to privacy.apple.com")
            print("2. Request a copy of your data")
            print("3. Select 'Apple Media Services information'")
            print("4. Extract the downloaded archive")
            print("5. Update APPLE_EXPORT_DIR in .env to point to 'Apple Music Activity' folder")
            sys.exit(1)

        required_files = [
            "Apple Music - Favorites.csv",
            "Apple Music - Play History Daily Tracks.csv"
        ]

        missing = []
        for filename in required_files:
            if not (self.export_dir / filename).exists():
                missing.append(filename)

        if missing:
            print(f"\nError: Missing required files in {self.export_dir}:")
            for f in missing:
                print(f"  - {f}")
            sys.exit(1)

    def _load_cached_stats(self) -> Optional[Dict]:
        """Load cached artist statistics if valid"""
        if self.stats_cache_file.exists():
            try:
                with open(self.stats_cache_file, 'r') as f:
                    cache = json.load(f)
                    cache_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
                    if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRY_DAYS):
                        artists = cache.get("artists", {})
                        # Convert ISO strings back to datetime objects
                        for artist_data in artists.values():
                            if artist_data.get("last_played"):
                                artist_data["last_played"] = datetime.fromisoformat(artist_data["last_played"])
                        return artists
            except Exception as e:
                print(f"Warning: Failed to load cache: {e}")
        return None

    def _save_cached_stats(self, stats: Dict):
        """Save artist statistics to cache"""
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
        with open(self.stats_cache_file, 'w') as f:
            json.dump(cache, f, indent=2)

    def _extract_artist_from_song_name(self, song_name: str) -> Optional[str]:
        """
        Extract artist name from 'Artist - Song Title' format

        Args:
            song_name: Song name from Play Activity (format: "Artist - Title")

        Returns:
            Artist name or None if extraction fails
        """
        if not song_name or not isinstance(song_name, str):
            return None

        # Handle "Artist - Song Title" format
        if ' - ' in song_name:
            parts = song_name.split(' - ', 1)
            if len(parts) >= 2 and parts[0].strip():
                return parts[0].strip()

        # Handle "Artist: Song Title" format (rare)
        if ': ' in song_name:
            parts = song_name.split(': ', 1)
            if len(parts) >= 2 and parts[0].strip():
                return parts[0].strip()

        return None

    def _parse_favorites(self, force_refresh: bool = False) -> Dict[str, Set[str]]:
        """
        Parse Favorites.csv to extract explicit likes/dislikes

        Args:
            force_refresh: If True, ignore cache and re-parse

        Returns:
            Dict with 'liked' and 'disliked' sets of artist names
        """
        favorites_file = self.export_dir / "Apple Music - Favorites.csv"

        # Check pickle cache (unless force refresh)
        if not force_refresh and self.favorites_pickle.exists():
            try:
                with open(self.favorites_pickle, 'rb') as f:
                    cached = pickle.load(f)
                    cache_time = cached.get("timestamp", datetime.min)
                    if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRY_DAYS):
                        print(f"✓ Using cached favorites data ({len(cached['liked'])} liked, {len(cached['disliked'])} disliked artists)")
                        return cached
            except Exception:
                pass

        print(f"Parsing favorites: {favorites_file.name}")

        try:
            df = pd.read_csv(favorites_file, encoding='utf-8')
        except Exception as e:
            print(f"Warning: Failed to parse favorites: {e}")
            return {"liked": set(), "disliked": set(), "timestamp": datetime.now()}

        liked_artists = set()
        disliked_artists = set()

        # Process each favorite entry
        for _, row in df.iterrows():
            if row['Favorite Type'] != 'Song':
                continue

            preference = row.get('Preference', 'NEUTRAL')
            item_desc = row.get('Item Description', '')

            # Extract artist from "Artist - Song" format
            artist = self._extract_artist_from_song_name(item_desc)
            if not artist:
                continue

            if preference == 'LIKE':
                liked_artists.add(artist)
                # Remove from disliked if previously disliked
                disliked_artists.discard(artist)
            elif preference == 'DISLIKE':
                disliked_artists.add(artist)
                # Remove from liked if previously liked
                liked_artists.discard(artist)

        result = {
            "liked": liked_artists,
            "disliked": disliked_artists,
            "timestamp": datetime.now()
        }

        # Cache results
        with open(self.favorites_pickle, 'wb') as f:
            pickle.dump(result, f)

        print(f"✓ Found {len(liked_artists)} liked artists, {len(disliked_artists)} disliked artists")
        return result

    def _parse_play_history(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Parse Play History Daily Tracks CSV with pickle caching for performance

        This file aggregates plays by day and includes "Artist - Song" in Track Description field,
        making it much simpler and faster to parse than the full Play Activity CSV.

        Args:
            force_refresh: If True, ignore cache and re-parse

        Returns:
            DataFrame with play history data
        """
        play_history_file = self.export_dir / "Apple Music - Play History Daily Tracks.csv"

        # Check pickle cache (unless force refresh)
        if not force_refresh and self.play_activity_pickle.exists():
            try:
                cached = pd.read_pickle(self.play_activity_pickle)
                cache_time = self.play_activity_pickle.stat().st_mtime
                if datetime.now().timestamp() - cache_time < CACHE_EXPIRY_DAYS * 86400:
                    print(f"✓ Using cached play history data ({len(cached):,} entries)")
                    return cached
            except Exception:
                pass

        print(f"Parsing play history: {play_history_file.name}")
        print(f"File size: {play_history_file.stat().st_size / 1024 / 1024:.1f} MB")

        # Only read columns we need for efficiency
        usecols = [
            'Track Description',
            'Date Played',
            'Hours',
            'Play Count',
            'Skip Count',
            'Play Duration Milliseconds',
            'End Reason Type'
        ]

        try:
            # Parse CSV
            print("Reading CSV...")
            df = pd.read_csv(
                play_history_file,
                usecols=usecols,
                encoding='utf-8',
                on_bad_lines='warn',
                engine='python'
            )

            # Convert date
            df['Date Played'] = pd.to_datetime(df['Date Played'], format='%Y%m%d', errors='coerce')

            # Calculate statistics
            oldest_play = df['Date Played'].min()
            newest_play = df['Date Played'].max()
            date_range_days = (newest_play - oldest_play).days if pd.notna(oldest_play) and pd.notna(newest_play) else 0
            date_range_years = date_range_days / 365.25

            # Store play history date statistics
            self.library_stats.update({
                "oldest_play": oldest_play.strftime('%d %B %Y') if pd.notna(oldest_play) else None,
                "newest_play": newest_play.strftime('%d %B %Y') if pd.notna(newest_play) else None,
                "history_span_years": round(date_range_years, 1) if date_range_days > 0 else 0,
                "history_span_days": date_range_days if date_range_days > 0 else 0
            })

            # Cache results
            print(f"Caching parsed data for future runs...")
            df.to_pickle(self.play_activity_pickle)

            print(f"✓ Parsed {len(df):,} play history entries")
            print(f"\nListening history statistics:")
            if pd.notna(oldest_play):
                print(f"  Oldest play: {oldest_play.strftime('%d %B %Y')}")
            if pd.notna(newest_play):
                print(f"  Newest play: {newest_play.strftime('%d %B %Y')}")
            if date_range_days > 0:
                print(f"  History span: {date_range_years:.1f} years ({date_range_days:,} days)")

            return df

        except Exception as e:
            print(f"Error parsing play history: {e}")
            print("Returning empty DataFrame")
            return pd.DataFrame()

    def _aggregate_by_artist(self, favorites: Dict, play_df: pd.DataFrame) -> Dict[str, Dict]:
        """
        Aggregate all data sources by artist

        Args:
            favorites: Dict with liked/disliked artist sets
            play_df: DataFrame with play activity

        Returns:
            Dict mapping artist names to statistics (same format as AppleMusicLibrary)
        """
        print("Aggregating statistics by artist...")

        artist_stats = defaultdict(lambda: {
            "play_count": 0,
            "loved": False,
            "disliked": False,
            "disliked_track_count": 0,
            "loved_track_count": 0,
            "rating": 0,
            "track_count": 0,
            "last_played": None,
            "skip_count": 0,
            "total_play_duration_ms": 0,
            "total_media_duration_ms": 0,
            "completion_rate": 0.0
        })

        # Process play history
        for _, row in play_df.iterrows():
            # Extract artist from "Artist - Song" format in Track Description
            track_desc = row.get('Track Description')
            artist = self._extract_artist_from_song_name(track_desc)

            if not artist or not isinstance(artist, str) or not artist.strip():
                continue

            # Aggregate play statistics (Play History has pre-aggregated counts)
            play_count = row.get('Play Count', 0)
            skip_count = row.get('Skip Count', 0)

            if pd.notna(play_count):
                artist_stats[artist]["play_count"] += int(play_count)

            if pd.notna(skip_count):
                artist_stats[artist]["skip_count"] += int(skip_count)

            # Track play duration
            play_duration = row.get('Play Duration Milliseconds', 0)
            if pd.notna(play_duration):
                # Multiply by play count since this is aggregated data
                artist_stats[artist]["total_play_duration_ms"] += play_duration * play_count

            # Track most recent play
            date_played = row.get('Date Played')
            if pd.notna(date_played):
                if artist_stats[artist]["last_played"] is None:
                    artist_stats[artist]["last_played"] = date_played
                elif date_played > artist_stats[artist]["last_played"]:
                    artist_stats[artist]["last_played"] = date_played

        # Apply favorites data (explicit likes/dislikes override inferred preferences)
        for artist in favorites["liked"]:
            if artist in artist_stats:
                artist_stats[artist]["loved"] = True
                artist_stats[artist]["loved_track_count"] = max(1, artist_stats[artist]["loved_track_count"])

        for artist in favorites["disliked"]:
            if artist in artist_stats:
                artist_stats[artist]["disliked"] = True
                artist_stats[artist]["disliked_track_count"] = max(1, artist_stats[artist]["disliked_track_count"])

        # Calculate completion rates
        for artist, stats in artist_stats.items():
            if stats["total_media_duration_ms"] > 0:
                stats["completion_rate"] = stats["total_play_duration_ms"] / stats["total_media_duration_ms"]
            else:
                stats["completion_rate"] = 0.0

            # Infer "rating" based on engagement (0-100 scale for compatibility)
            # High completion rate + low skips + many plays = high rating
            if stats["play_count"] > 0:
                skip_penalty = stats["skip_count"] / stats["play_count"]
                engagement_score = stats["completion_rate"] * (1 - skip_penalty)
                stats["rating"] = min(100, int(engagement_score * 100))

        # Calculate aggregate statistics
        total_plays = sum(s["play_count"] for s in artist_stats.values())
        total_skips = sum(s["skip_count"] for s in artist_stats.values())
        skip_rate = (total_skips / total_plays * 100) if total_plays > 0 else 0

        # Store aggregate stats (will be updated with play history stats in get_artist_stats)
        self.library_stats.update({
            "total_artists": len(artist_stats),
            "total_plays": total_plays,
            "total_skips": total_skips,
            "skip_rate": skip_rate
        })

        print(f"✓ Aggregated statistics for {len(artist_stats)} artists")
        print(f"  Total plays: {total_plays:,}")
        print(f"  Total skips: {total_skips:,} ({skip_rate:.1f}%)")

        return dict(artist_stats)

    def get_artist_stats(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Extract artist statistics from Apple Music export data

        Args:
            force_refresh: If True, ignore cache and re-parse export data

        Returns:
            Dict with artist names as keys and stats as values (compatible with AppleMusicLibrary format)
        """
        # Check cache first
        if not force_refresh:
            cached = self._load_cached_stats()
            if cached:
                print(f"Using cached Apple Music export data ({len(cached)} artists)")
                print("Use --scan-library to force a fresh scan")
                return cached

        # Parse export data
        favorites = self._parse_favorites(force_refresh=force_refresh)
        play_df = self._parse_play_history(force_refresh=force_refresh)

        # Aggregate by artist
        stats = self._aggregate_by_artist(favorites, play_df)

        # Store loved/disliked counts in library stats
        self.library_stats.update({
            "loved_artists": len(favorites["liked"]),
            "disliked_artists": len(favorites["disliked"])
        })

        # Cache results
        self._save_cached_stats(stats)
        print("✓ Apple Music export data cached for future runs")

        return stats

    def get_library_stats(self) -> Dict:
        """
        Get library statistics (oldest play, history span, total plays, etc.)

        Returns:
            Dict with library statistics or empty dict if not available
        """
        return self.library_stats.copy()
