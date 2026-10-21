"""Small text normalisation helpers shared by the matcher, diff engine and evaluator."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    """Lower-case, '&' -> 'and', strip punctuation, collapse whitespace."""
    text = (text or "").lower().replace("&", " and ")
    return _NON_ALNUM.sub(" ", text).strip()


def title_case(text: str) -> str:
    """Title-case while keeping short connector words lower-case and '&' intact."""
    small = {"and", "or", "of", "to", "the", "a", "an", "in", "on", "for"}
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i > 0 and lw in small:
            out.append(lw)
        elif w.isupper() and len(w) <= 4:
            out.append(w)  # keep acronyms such as "5G" or "FAQ"
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def path_words(url_or_path: str) -> str:
    """'/phones/nimbus-x15.html' -> 'phones nimbus x15'; '/' -> 'home index'."""
    path = urlparse(url_or_path).path or url_or_path
    path = re.sub(r"\.(html?|php|aspx?)$", "", path)
    words = norm(path.replace("index", " "))
    return words or "home index"
