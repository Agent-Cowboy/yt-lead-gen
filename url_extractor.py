"""
url_extractor.py — YouTube URL/handle validation and parsing.
Accepts YouTube channel URLs, @handles, and various URL formats.
Extracts handles from messy text (e.g. "@mkbhd•15 subscribers").
Returns a deduplicated list of normalized channel URLs (max 30).
"""

import re
from urllib.parse import urlparse

# Maximum channels allowed per request
MAX_CHANNELS = 30

# Regex to find @handles anywhere in a line of text
HANDLE_PATTERN = re.compile(r'@([\w.-]{1,100})')

# Regex to find full YouTube channel URLs anywhere in text
URL_PATTERN = re.compile(
    r'https?://(www\.)?youtube\.com/'
    r'(@[\w.-]+|c/[\w.-]+|channel/[\w-]+|user/[\w.-]+)'
)


def _normalize_input(line: str) -> str:
    """Strip whitespace and trailing slashes from a single line."""
    return line.strip().rstrip('/')


def _extract_from_line(line: str) -> str | None:
    """
    Try to extract a YouTube channel reference from a line of text.
    Handles messy inputs like "@mkbhd•15 subscribers" or full URLs.
    """
    cleaned = _normalize_input(line)
    if not cleaned:
        return None

    # First: try to find a full YouTube URL in the line
    url_match = URL_PATTERN.search(cleaned)
    if url_match:
        path = url_match.group(2)
        return f'https://www.youtube.com/{path}'

    # Second: try to find an @handle anywhere in the line
    handle_match = HANDLE_PATTERN.search(cleaned)
    if handle_match:
        handle = handle_match.group(0)  # includes the @
        return f'https://www.youtube.com/{handle}'

    return None


def extract_channels(raw_text: str) -> list[str]:
    """
    Parse raw textarea input into a list of validated,
    deduplicated YouTube channel URLs.

    Args:
        raw_text: Multi-line string from user input with URLs/handles

    Returns:
        List of normalized YouTube channel URLs (max MAX_CHANNELS)

    Raises:
        ValueError: If no valid channels found or input is empty
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Input is empty. Please provide YouTube channel URLs or @handles.")

    lines = raw_text.strip().split('\n')
    seen = set()
    channels = []

    for line in lines:
        url = _extract_from_line(line)
        if not url:
            continue

        # Deduplicate by lowercase URL
        key = url.lower()
        if key not in seen:
            seen.add(key)
            channels.append(url)

    if not channels:
        raise ValueError(
            "No valid YouTube channels detected. "
            "Please use formats like @handle or https://youtube.com/@handle"
        )

    if len(channels) > MAX_CHANNELS:
        channels = channels[:MAX_CHANNELS]

    return channels


def count_valid_channels(raw_text: str) -> int:
    """
    Count how many valid channels are in the input without raising errors.
    Used for the real-time counter in the frontend.
    """
    try:
        return len(extract_channels(raw_text))
    except ValueError:
        return 0
