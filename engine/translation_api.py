"""Use the Azure Translator F0 text API before the offline Argos fallback."""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Sequence

import requests

logger = logging.getLogger(__name__)
AZURE_URL = "https://api.cognitive.microsofttranslator.com/translate"


class TranslationAPIError(Exception):
    """An API response cannot be used as a complete translation batch."""


class AzureTranslator:
    def __init__(self, key: str, region: str = "", *, session: requests.Session | None = None, chars_per_second: int = 120):
        self.session = session or requests.Session()
        self.headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json"}
        if region:
            self.headers["Ocp-Apim-Subscription-Region"] = region
        self.chars_per_second = chars_per_second
        self.next_allowed_at = 0.0

    def translate_many(self, texts: Sequence[str]) -> list[str]:
        if not texts:
            return []
        total_chars = sum(len(text) for text in texts)
        if total_chars > 50_000 or len(texts) > 1_000:
            raise TranslationAPIError("batch exceeds Azure Translator request limits")
        delay = self.next_allowed_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        # Four parallel shards each stay below one quarter of the F0 hourly rate.
        self.next_allowed_at = time.monotonic() + total_chars / self.chars_per_second
        try:
            response = self.session.post(
                AZURE_URL,
                params={"api-version": "3.0", "from": "en", "to": "zh-Hans"},
                headers=self.headers,
                json=[{"Text": text} for text in texts],
                timeout=(10, 45),
            )
        except requests.RequestException as error:
            raise TranslationAPIError("network request failed") from error
        if response.status_code != 200:
            raise TranslationAPIError(f"HTTP {response.status_code}")
        try:
            payload = response.json()
            results = [item["translations"][0]["text"].strip() for item in payload]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise TranslationAPIError("invalid API response") from error
        if len(results) != len(texts) or not all(results):
            raise TranslationAPIError("incomplete API response")
        return results


class ApiFirstTranslator:
    """Disable the API after an error and lazily load the offline model."""

    def __init__(self, fallback_factory: Callable[[], Callable[[str], str]], *, api: AzureTranslator | None = None):
        self.api = api
        self.fallback_factory = fallback_factory
        self.fallback: Callable[[str], str] | None = None

    @classmethod
    def from_environment(cls, fallback_factory: Callable[[], Callable[[str], str]]) -> ApiFirstTranslator:
        key = os.environ.get("AZURE_TRANSLATOR_F0_KEY", "").strip()
        region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
        return cls(fallback_factory, api=AzureTranslator(key, region) if key else None)

    def translate_many(self, texts: Sequence[str]) -> list[tuple[str, str]]:
        if self.api:
            try:
                return [(result, "azure-f0") for result in self.api.translate_many(texts)]
            except TranslationAPIError as error:
                logger.warning("Azure Translator unavailable (%s); using offline model for remaining text", error)
                self.api = None
        if self.fallback is None:
            self.fallback = self.fallback_factory()
        return [(self.fallback(text), "argos") for text in texts]

    def __call__(self, text: str) -> str:
        return self.translate_many([text])[0][0]
