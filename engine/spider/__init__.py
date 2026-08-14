"""Importing this package registers every spider into the registry.

Keep this file free of logic; it exists only for the registration
side-effects of the spider modules below.
"""
from engine.spider import arxiv, bilibili, biorxiv, rss, zhihu  # noqa: F401