"""Code-aware tokenizer for BM25 retrieval.

Preserves full original identifiers while decomposing them into:
- snake_case components
- camelCase & PascalCase components
- dotted module / member components
- Python keywords and docstring natural language tokens

Never destroys original identifiers.
"""
from __future__ import annotations

import re
from typing import List


def _expand_camel(ident: str, tokens: List[str]) -> None:
    """Split camelCase and PascalCase identifiers into lowercased parts."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", ident)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    if "_" in s2:
        for sub in s2.split("_"):
            sub_low = sub.lower()
            if sub_low and (not tokens or tokens[-1] != sub_low):
                tokens.append(sub_low)


def _expand_identifier(ident: str, tokens: List[str]) -> None:
    """Expand snake_case or single identifier into constituent sub-tokens."""
    if "_" in ident:
        for part in ident.split("_"):
            if part:
                part_low = part.lower()
                if not tokens or tokens[-1] != part_low:
                    tokens.append(part_low)
                _expand_camel(part, tokens)
    else:
        _expand_camel(ident, tokens)


def tokenize_code(text: str) -> List[str]:
    """Tokenize source code or search query into a sequence of search terms.

    Supports:
    - full dotted paths (e.g. 'app.services.users')
    - compound identifiers (e.g. 'UserRepository.find_by_id')
    - snake_case (e.g. 'get_user_profile' -> ['get_user_profile', 'get', 'user', 'profile'])
    - camelCase & PascalCase (e.g. 'UserService' -> ['userservice', 'user', 'service'])
    - natural language prose and docstrings

    Returns:
        List of lowercased token strings in deterministic order.
    """
    if not text:
        return []

    tokens: List[str] = []
    # Match dotted identifiers, snake_case, camelCase, alphanumeric words
    raw_tokens = re.findall(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", text)

    for raw in raw_tokens:
        clean = raw.strip(".")
        if not clean:
            continue
        low = clean.lower()
        tokens.append(low)

        if "." in clean:
            # Dotted member or import path
            for dot_part in clean.split("."):
                if dot_part:
                    part_low = dot_part.lower()
                    if tokens[-1] != part_low:
                        tokens.append(part_low)
                    _expand_identifier(dot_part, tokens)
        else:
            _expand_identifier(clean, tokens)

    return tokens
