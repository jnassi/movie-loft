"""The streaming services Movie Loft can tune to, in one place.

Shows you stream but don't own come from [streaming] in corrections.toml
(fetch_streaming.py). For each episode, Apple's catalog (tv.apple.com, the
data behind the Apple TV app's "Watch on…" choices) lists every service that
carries it, with that service's own "play this episode" link. Tune in opens
that link on the Apple TV, which starts the episode in the service's app.

Each entry: the name Movie Loft shows (also what you write in
corrections.toml), other names you might write, the service's name in Apple's
catalog, its TMDB watch-provider IDs (US), and the start of its play links —
the server only accepts links that start with one of these.

Apple TV+ plays inside the Apple TV app, so it keeps using tv.apple.com links
(no prefix here). Netflix isn't in Apple's catalog at all, so it can't be
supported this way.
"""
import re

SERVICES = {
    "Apple TV+":   {"aka": ["Apple TV"], "apple": "Apple TV", "tmdb": [350], "links": []},
    "HBO Max":     {"aka": ["Max", "HBO"], "apple": "HBO Max", "tmdb": [1899, 1825],
                    "links": ["https://play.hbomax.com/"]},
    "Hulu":        {"aka": [], "apple": "Hulu", "tmdb": [15], "links": ["hulu://"]},
    "Disney+":     {"aka": ["Disney Plus"], "apple": "Disney+", "tmdb": [337],
                    "links": ["https://www.disneyplus.com/play/"]},
    "Prime Video": {"aka": ["Amazon Prime Video", "Amazon Prime", "Prime", "Amazon"], "apple": "Prime Video",
                    "tmdb": [9, 2100], "links": ["aiv://aiv/watch?"]},
    "Paramount+":  {"aka": ["Paramount Plus", "Paramount"], "apple": "Paramount+",
                    "tmdb": [2303, 2616, 1853, 582, 633], "links": ["pplus://www.paramountplus.com/"]},
    "Peacock":     {"aka": ["Peacock Premium"], "apple": "Peacock", "tmdb": [386, 387],
                    "links": ["https://www.peacocktv.com/deeplink?"]},
}

LINK_PREFIXES = tuple(p for s in SERVICES.values() for p in s["links"])


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("+", "plus"))


def canonical(name):
    """'Max' → 'HBO Max', 'disney plus' → 'Disney+'; None if unsupported."""
    n = _norm(name)
    for key, s in SERVICES.items():
        if n == _norm(key) or n in map(_norm, s["aka"]):
            return key
    return None


def play_link(service, url):
    """A service's play link as Tune in should send it. Prime Video's carry
    time=auto ("resume where you left off"): on an episode already watched
    that resumes at the end, autoplay rolls into the next episode, and the
    jump lands in the wrong one (tested Oct 2026). time=0 starts at the top."""
    if service == "Prime Video":
        url = url.replace("time=auto", "time=0")
    return url


def is_play_link(link):
    """A service's own play link (not tv.apple.com)."""
    return link.startswith(LINK_PREFIXES)
