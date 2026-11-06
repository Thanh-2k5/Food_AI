import re
import unicodedata


def normalize_ingredient_name(name):
    normalized = unicodedata.normalize(
        'NFKD',
        name.casefold().replace('đ', 'd').replace('_', ' ')
    )
    normalized_characters = ''.join(
        character if character.isalnum() else ' '
        for character in normalized
        if not unicodedata.combining(character)
    )
    return ' '.join(normalized_characters.split())


def canonical_ingredient_name(name):
    return re.sub(r'\s+', '_', normalize_ingredient_name(name))
