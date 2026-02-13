# List of languages for subtitles
# Format: (language_code, language_name) - Using ISO 639-2 codes
LANGUAGES = [
    ('eng', 'English'),
    ('pol', 'Polski'),
    ('spa', 'Español'),
    ('fra', 'Français'),
    ('deu', 'Deutsch'),
    ('ita', 'Italiano'),
    ('por', 'Português'),
    ('pob', 'Português (Brasil)'),
    ('rus', 'Русский'),
    ('jpn', '日本語'),
    ('zho', '中文'),  # ISO 639-2/T for Chinese
    ('kor', '한국어'),
    ('ara', 'العربية'),
    ('hin', 'हिन्दी'),
    ('tur', 'Türkçe'),
    ('nld', 'Nederlands'),
    ('swe', 'Svenska'),
    ('nor', 'Norsk'),
    ('dan', 'Dansk'),
    ('fin', 'Suomi'),
    ('ces', 'Čeština'),
    ('slk', 'Slovenčina'),
    ('hun', 'Magyar'),
    ('ron', 'Română'),
    ('bul', 'Български'),
    ('ell', 'Ελληνικά'),
    ('heb', 'עברית'),
    ('tha', 'ไทย'),
    ('vie', 'Tiếng Việt'),
    ('ind', 'Bahasa Indonesia'),
    ('msa', 'Bahasa Melayu'),    # ISO 639-2/T for Malay
    ('ukr', 'Українська'),
    ('srp', 'Српски'),
    ('hrv', 'Hrvatski'),
    ('slv', 'Slovenščina'),
    ('est', 'Eesti'),
    ('lav', 'Latviešu'),
    ('lit', 'Lietuvių'),
    ('fas', 'فارسی'),  # ISO 639-2/B for Persian (Farsi)
    ('urd', 'اردو'),
    ('ben', 'বাংলা'),
    ('mya', 'မြန်မာ'), # ISO 639-2/T for Burmese
    ('cat', 'Català'),
    ('eus', 'Euskara'),
    ('epo', 'Esperanto'),
    ('mkd', 'Македонски'),
    ('tel', 'తెలుగు'), 
    ('sqi', 'Shqip') 
]

# Dictionary for quick lookups
LANGUAGE_DICT = dict(LANGUAGES)


def get_language_name(code):
    """Get language name from language code."""
    return LANGUAGE_DICT.get(code, code)
