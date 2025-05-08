# List of languages for subtitles
# Format: (language_code, language_name)
LANGUAGES = [
    ('en', 'English'),
    ('pl', 'Polish'),
    ('es', 'Spanish'),
    ('fr', 'French'),
    ('de', 'German'),
    ('it', 'Italian'),
    ('pt', 'Portuguese'),
    ('ru', 'Russian'),
    ('ja', 'Japanese'),
    ('zh', 'Chinese'),
    ('ko', 'Korean'),
    ('ar', 'Arabic'),
    ('hi', 'Hindi'),
    ('tr', 'Turkish'),
    ('nl', 'Dutch'),
    ('sv', 'Swedish'),
    ('no', 'Norwegian'),
    ('da', 'Danish'),
    ('fi', 'Finnish'),
    ('cs', 'Czech'),
    ('sk', 'Slovak'),
    ('hu', 'Hungarian'),
    ('ro', 'Romanian'),
    ('bg', 'Bulgarian'),
    ('el', 'Greek'),
    ('he', 'Hebrew'),
    ('th', 'Thai'),
    ('vi', 'Vietnamese'),
    ('id', 'Indonesian'),
    ('ms', 'Malay'),
    ('uk', 'Ukrainian'),
    ('sr', 'Serbian'),
    ('hr', 'Croatian'),
    ('sl', 'Slovenian'),
    ('et', 'Estonian'),
    ('lv', 'Latvian'),
    ('lt', 'Lithuanian'),
    ('fa', 'Persian'),
    ('ur', 'Urdu'),
    ('bn', 'Bengali')
]

# Dictionary for quick lookups
LANGUAGE_DICT = dict(LANGUAGES)


def get_language_name(code):
    """Get language name from language code."""
    return LANGUAGE_DICT.get(code, code)
