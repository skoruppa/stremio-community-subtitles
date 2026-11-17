import re

_TAG_EXTENSION = re.compile(r'\.[a-z][a-z0-9]{1,4}$')
_CRC = re.compile(r'[\[(][0-9a-f]{8}[\])]')
_FRAME_RATE = re.compile(r'(?<![0-9])(?:23\.976?|23\.98|29\.97|59\.94|(?:24|25|30|50|60)\.000?)(?:\s*fps)?(?![0-9])')
_AUDIO_CHANNELS = re.compile(r'(?<![0-9])[257]\.[01](?![0-9])')
_CODEC = re.compile(r'[hx]\.?26[45]|\d{1,2}[ .-]?bits?')
_VERSION_SUFFIX = re.compile(r'(?<=\d)v\d(?![0-9])')
_SEPARATORS = re.compile(r'[._]+')
_RESOLUTION = re.compile(r'(?<![a-z0-9])(?:\d{3,4}[pi]|\d{3,4}x\d{3,4}|[248]k)(?![a-z0-9])')
_SEASON_EPISODE = re.compile(r'(?<![a-z0-9])s(\d{1,2})\s*e(\d{1,4})(?:\s*(?:-|~|e)\s*e?(\d{1,4}))?(?![0-9])')
_CROSS_EPISODE = re.compile(r'(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![a-z0-9])')
_SEASON_WORD = re.compile(r'(?<![a-z])(?:season|saison|sezon|series|part|cour|vol(?:ume)?)\s*\d+')
_EPISODE_MARKER = re.compile(r'(?<![a-z])(?:(?:episode|episodio|odcinek|odc|folge|ep)\s*|e|#)(\d{1,4})(?![0-9])')
_RANGE = re.compile(r'(?<![a-z0-9])(\d{1,4})\s*[-~]\s*(\d{1,4})(?![a-z0-9])')
_NUMBER = re.compile(r'(?<![a-z0-9])(\d{1,4})(?![a-z0-9])')


def _normalize(name):
    name = name.strip().lower()
    name = _TAG_EXTENSION.sub('', name)
    name = _CRC.sub(' ', name)
    name = _FRAME_RATE.sub(' ', name)
    name = _AUDIO_CHANNELS.sub(' ', name)
    name = _CODEC.sub(' ', name)
    name = _VERSION_SUFFIX.sub('', name)
    name = _SEPARATORS.sub(' ', name)
    return _RESOLUTION.sub(' ', name)


def _season_episodes(name):
    episodes = []
    for season, first, last in _SEASON_EPISODE.findall(name):
        first = int(first)
        last = int(last) if last else first
        episodes.append((int(season), first, max(first, last)))
    for season, episode in _CROSS_EPISODE.findall(name):
        episodes.append((int(season), int(episode), int(episode)))
    return episodes


def _bare_episode_numbers(name):
    name = _SEASON_WORD.sub(' ', name)
    ranges = []

    def take_range(match):
        first, last = int(match.group(1)), int(match.group(2))
        if first < last:
            ranges.append((first, last))
            return ' '
        return match.group(0)

    name = _RANGE.sub(take_range, name)
    numbers = {int(n) for n in _EPISODE_MARKER.findall(name)}
    numbers.update(int(n) for n in _NUMBER.findall(name))
    return numbers, ranges


def _is_year(number):
    return 1900 <= number <= 2099


def numbers_outside_episode(video_filename, *episodes):
    if not video_filename:
        return set()
    name = _normalize(video_filename)
    if _season_episodes(name):
        name = _SEASON_EPISODE.sub(' ', name)
        name = _CROSS_EPISODE.sub(' ', name)
    numbers, _ = _bare_episode_numbers(name)
    return {n for n in numbers if n not in episodes}


def _segment_matches(segment, season, episode, ignored_numbers, alternate_episode):
    name = _normalize(segment)
    labelled = _season_episodes(name)
    comparable = [
        (first, last)
        for release_season, first, last in labelled
        if season is None or release_season == season
    ]
    if comparable:
        return any(first <= episode <= last for first, last in comparable)
    if labelled or season not in (None, 1):
        return True

    numbers, ranges = _bare_episode_numbers(name)
    accepted = {episode, alternate_episode} - {None}
    if accepted & numbers or any(first <= ep <= last for ep in accepted for first, last in ranges):
        return True
    meaningful = {n for n in numbers if n not in ignored_numbers and not _is_year(n)}
    return not meaningful and not ranges


def release_matches_episode(release_name, season, episode, ignored_numbers=frozenset(), alternate_episode=None):
    if not release_name or not episode:
        return True
    segments = [s for s in release_name.split(';') if s.strip()] or [release_name]
    return any(_segment_matches(s, season, episode, ignored_numbers, alternate_episode) for s in segments)
