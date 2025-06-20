from typing import List, Tuple
from app.domain.models import Item

MANDATORY_FIELDS = ("statement", "options", "answer")

def validate_items(items: List[Item]) -> Tuple[List[Item], List[Item]]:
    valid, invalid = [], []
    for it in items:
        (valid if all(getattr(it, f, None) for f in MANDATORY_FIELDS) else invalid).append(it)
    return valid, invalid
