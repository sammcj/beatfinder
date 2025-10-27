#!/usr/bin/env python3
"""
Apple Music integration: scrape song links from catalogue
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime, timedelta
import re
import json


# Cache settings
APPLE_MUSIC_CACHE_FILE = Path("cache/apple_music_scrape_cache.json")
APPLE_MUSIC_CACHE_EXPIRY_DAYS = 7  # Re-scrape after 7 days


def load_scrape_cache() -> Dict[str, Dict]:
    """
    Load cached Apple Music scraping results.

    Returns:
        Dict mapping artist names to their scraped data with metadata
        Format: {
            'artist_name': {
                'data': {'artist_url': '...', 'songs': [...]},
                'cached_at': '2025-10-28T10:30:00',
                'cache_version': 1
            }
        }
    """
    if not APPLE_MUSIC_CACHE_FILE.exists():
        return {}

    try:
        with open(APPLE_MUSIC_CACHE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load Apple Music cache: {e}")
        return {}


def save_scrape_cache(cache_data: Dict[str, Dict]):
    """Save Apple Music scraping cache to disk"""
    APPLE_MUSIC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(APPLE_MUSIC_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save Apple Music cache: {e}")


def is_cache_entry_valid(cache_entry: Dict) -> bool:
    """Check if a cache entry is still valid (not expired)"""
    try:
        cached_at = datetime.fromisoformat(cache_entry.get('cached_at', ''))
        age = datetime.now() - cached_at
        return age < timedelta(days=APPLE_MUSIC_CACHE_EXPIRY_DAYS)
    except Exception:
        return False


class AppleMusicScraper:
    """Scrape Apple Music web catalogue for artist songs"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser = None

    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def search_artist_songs(self, artist_name: str, max_songs: int = 3) -> Dict[str, any]:
        """
        Search for an artist and return their top songs with URLs and IDs

        Args:
            artist_name: Name of the artist to search for
            max_songs: Maximum number of songs to return

        Returns:
            Dict with 'artist_url', 'songs' (list of {title, url, id})
        """
        if not self.browser:
            raise RuntimeError("Scraper not initialised. Use with context manager.")

        try:
            page = self.browser.new_page()

            # Navigate to Apple Music search
            search_url = f"https://music.apple.com/us/search?term={artist_name.replace(' ', '+')}"
            page.goto(search_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Find first artist link and navigate to artist page
            first_artist = page.query_selector('a[href*="/artist/"]')
            if not first_artist:
                page.close()
                return {'artist_url': None, 'songs': []}

            artist_url = first_artist.get_attribute('href')
            if not artist_url.startswith('http'):
                artist_url = f"https://music.apple.com{artist_url}"

            # Navigate to artist page
            page.goto(artist_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Get page text and HTML to extract song titles and IDs
            page_text = page.inner_text('body')
            page_html = page.content()
            songs = self._extract_top_songs(page_text, page_html, artist_name, artist_url, max_songs)

            page.close()
            return {
                'artist_url': artist_url,
                'songs': songs
            }

        except PlaywrightTimeout:
            return {'artist_url': None, 'songs': []}
        except Exception as e:
            print(f"Error scraping {artist_name}: {e}")
            return {'artist_url': None, 'songs': []}

    def _extract_top_songs(self, page_text: str, page_html: str, artist_name: str, artist_url: str, max_songs: int) -> List[Dict[str, str]]:
        """Extract song titles and IDs from the Top Songs section of an artist page"""
        if "Top Songs" not in page_text:
            return []

        # Extract all song IDs from the HTML
        song_id_matches = re.findall(r'/song/[^/\"\']+/(\d+)', page_html)
        song_ids = list(dict.fromkeys(song_id_matches))  # Remove duplicates, preserve order

        lines = page_text.split('\n')
        top_songs_idx = None

        # Find "Top Songs" section
        for i, line in enumerate(lines):
            if line.strip() == "Top Songs":
                top_songs_idx = i
                break

        if top_songs_idx is None:
            return []

        # Extract song titles
        songs = []
        i = top_songs_idx + 1
        collected_titles = []
        song_idx = 0

        while i < len(lines) and len(songs) < max_songs:
            line = lines[i].strip()

            # Stop at Albums section
            if line == "Albums":
                break

            # Skip empty lines, year patterns, and album info
            if line and not re.match(r'^[\d\s·]+$', line):
                # Check if line looks like album/year info (usually after song title)
                if re.match(r'^.+\s+·\s+\d{4}$', line):
                    i += 1
                    continue

                # This looks like a song title
                if line not in collected_titles:
                    collected_titles.append(line)

                    # Try to get the corresponding song ID (they should be in order)
                    song_id = song_ids[song_idx] if song_idx < len(song_ids) else None
                    song_idx += 1

                    if song_id:
                        # Create direct song URL using the ID
                        song_url = f"music://music.apple.com/us/song/{song_id}"
                        web_song_url = f"https://music.apple.com/us/song/{song_id}"
                    else:
                        # Fallback to search URL
                        search_query = f"{line} {artist_name}"
                        song_url = f"music://music.apple.com/search?term={search_query.replace(' ', '+')}"
                        web_song_url = f"https://music.apple.com/us/search?term={search_query.replace(' ', '+')}"

                    songs.append({
                        'title': line,
                        'url': song_url,
                        'web_url': web_song_url,
                        'id': song_id
                    })

            i += 1

        return songs[:max_songs]


def scrape_artists_parallel(artist_names: List[str], max_songs: int = 3, batch_size: int = 5) -> Dict[str, Dict]:
    """
    Scrape multiple artists in parallel batches with caching.

    Args:
        artist_names: List of artist names to search
        max_songs: Max songs per artist
        batch_size: Number of concurrent browser instances

    Returns:
        Dict mapping artist names to their song data
    """
    # Load cache
    cache = load_scrape_cache()
    results = {}
    artists_to_scrape = []
    cached_count = 0

    # Check cache for each artist
    for artist in artist_names:
        cache_entry = cache.get(artist)
        if cache_entry and is_cache_entry_valid(cache_entry):
            # Use cached data
            results[artist] = cache_entry['data']
            cached_count += 1
        else:
            # Need to scrape
            artists_to_scrape.append(artist)

    total_artists = len(artist_names)
    print(f"  ✓ Using cached data for {cached_count}/{total_artists} artists")

    if not artists_to_scrape:
        print(f"  All artists cached - no scraping needed!\n")
        return results

    print(f"  Scraping {len(artists_to_scrape)} new/expired artists...\n")

    completed = 0

    # Process in batches to avoid too many concurrent browsers
    for i in range(0, len(artists_to_scrape), batch_size):
        batch = artists_to_scrape[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(artists_to_scrape) + batch_size - 1) // batch_size

        print(f"  Batch {batch_num}/{total_batches}: Scraping {len(batch)} artists...")

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            # Create scraper instances for this batch
            futures = {}
            for artist in batch:
                future = executor.submit(_scrape_single_artist, artist, max_songs)
                futures[future] = artist

            # Collect results
            for future in as_completed(futures):
                artist = futures[future]
                completed += 1
                try:
                    data = future.result()
                    results[artist] = data
                    songs_found = len(data.get('songs', []))
                    status = f"✓ {songs_found} songs" if songs_found > 0 else "✗ no songs"
                    print(f"    [{completed}/{len(artists_to_scrape)}] {artist}: {status}")

                    # Update cache
                    cache[artist] = {
                        'data': data,
                        'cached_at': datetime.now().isoformat(),
                        'cache_version': 1
                    }
                except Exception as e:
                    print(f"    [{completed}/{len(artists_to_scrape)}] {artist}: ✗ error - {e}")
                    results[artist] = {'artist_url': None, 'songs': []}

    # Save updated cache
    save_scrape_cache(cache)

    return results


def _scrape_single_artist(artist_name: str, max_songs: int) -> Dict:
    """Helper to scrape a single artist (for parallel execution)"""
    with AppleMusicScraper() as scraper:
        return scraper.search_artist_songs(artist_name, max_songs)


def create_apple_music_playlist_with_scraping(
    recommendations: List[Dict],
    limit: int,
    songs_per_artist: int = 3,
    batch_size: int = 5
) -> Dict[str, any]:
    """
    Scrape Apple Music catalogue for song links

    Args:
        recommendations: List of recommendation dicts
        limit: Number of artists to process
        songs_per_artist: Songs to scrape per artist
        batch_size: Parallel scraping batch size

    Returns:
        Dict with 'artist_data' (mapping artist -> songs/urls)
    """
    print(f"\nScraping Apple Music catalogue for top {songs_per_artist} songs from {limit} artists...")
    print(f"Processing in batches of {batch_size} (parallel)...\n")

    # Scrape all artists in parallel
    artist_names = [rec['name'] for rec in recommendations[:limit]]
    print(f"Scraping {len(artist_names)} artists from Apple Music catalogue...\n")
    artist_data = scrape_artists_parallel(artist_names, songs_per_artist, batch_size)
    print(f"\n✓ Scraping complete\n")

    total_songs = sum(len(data.get('songs', [])) for data in artist_data.values())
    print(f"✓ Found {total_songs} songs with direct Apple Music links")
    print(f"   Click song links in recommendations.md to preview and add to your library\n")

    return {
        'artist_data': artist_data
    }


