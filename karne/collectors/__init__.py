"""Collectors: independent, single-responsibility measurement modules.

Each collector exposes ``collect(domain) -> dict`` and returns RAW, uninterpreted
observations only. Collectors never score, grade, or judge a domain (see CLAUDE.md,
immutable rule 1). If one collector fails, the scan continues with a partial result.
"""
