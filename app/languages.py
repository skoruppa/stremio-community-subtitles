# List of languages for subtitles
# Format: (language_code, language_name) - Using ISO 639-2 codes
LANGUAGES = [
    ('eng', 'English'),
    ('pol', 'Polish'),
    ('spa', 'Spanish'),
    ('fra', 'French'),
    ('deu', 'German'),
    ('ita', 'Italian'),
    ('por', 'Portuguese'),
    ('rus', 'Russian'),
    ('jpn', 'Japanese'),
    ('zho', 'Chinese'),  # ISO 639-2/T for Chinese
    ('kor', 'Korean'),
    ('ara', 'Arabic'),
    ('hin', 'Hindi'),
    ('tur', 'Turkish'),
    ('nld', 'Dutch'),
    ('swe', 'Swedish'),
    ('nor', 'Norwegian'),
    ('dan', 'Danish'),
    ('fin', 'Finnish'),
    ('ces', 'Czech'),
    ('slk', 'Slovak'),
    ('hun', 'Hungarian'),
    ('ron', 'Romanian'),
    ('bul', 'Bulgarian'),
    ('ell', 'Greek'),
    ('heb', 'Hebrew'),
    ('tha', 'Thai'),
    ('vie', 'Vietnamese'),
    ('ind', 'Indonesian'),
    ('msa', 'Malay'),    # ISO 639-2/T for Malay
    ('ukr', 'Ukrainian'),
    ('srp', 'Serbian'),
    ('hrv', 'Croatian'),
    ('slv', 'Slovenian'),
    ('est', 'Estonian'),
    ('lav', 'Latvian'),
    ('lit', 'Lithuanian'),
    ('fas', 'Persian'),  # ISO 639-2/B for Persian (Farsi)
    ('urd', 'Urdu'),
    ('ben', 'Bengali')
]

# Dictionary for quick lookups
LANGUAGE_DICT = dict(LANGUAGES)


def get_language_name(code):
    """Get language name from language code."""
    return LANGUAGE_DICT.get(code, code)
