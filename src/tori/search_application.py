"""Presentation-neutral web-search request and consent policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .search import (
    SearchConsent,
    explicit_search_query,
    is_bare_search_request,
    search_category_for_query,
    should_propose_search,
    weather_location_for_query,
)
from .source_retrieval import explicit_source_urls
from .user_settings import CapabilitySettingsController, UserSettingsError


SearchDisposition = Literal[
    "normal",
    "authorized",
    "proposal",
    "declined",
    "clarification",
    "weather_location_clarification",
    "disabled",
    "unavailable",
    "settings_failure",
]
SearchDecisionSource = Literal[
    "ordinary",
    "explicit",
    "consent",
    "bare",
    "freshness",
    "external_knowledge",
    "direct_url",
]


@dataclass(frozen=True, slots=True)
class SearchDecision:
    disposition: SearchDisposition
    query: str | None = None
    source: SearchDecisionSource = "ordinary"
    source_urls: tuple[str, ...] = ()


class SearchApplicationPolicy:
    """Decide search authority without executing or presenting a search."""

    def __init__(
        self,
        consent: SearchConsent,
        *,
        implementation_available: Callable[[], bool],
        capability_settings: CapabilitySettingsController | None,
        source_retrieval_available: Callable[[], bool] = lambda: False,
    ) -> None:
        self._consent = consent
        self._implementation_available = implementation_available
        self._capability_settings = capability_settings
        self._source_retrieval_available = source_retrieval_available

    def evaluate(
        self, text: str, *, conversation_id: str | None
    ) -> SearchDecision:
        source_urls = explicit_source_urls(text)
        explicit = explicit_search_query(text)
        consent_decision, confirmed_query = self._consent.resolve(
            text, conversation_id
        )
        if explicit is not None:
            self._consent.clear()
            if self._weather_location_missing(explicit):
                self._consent.propose_weather_location(
                    explicit, conversation_id, directly_authorized=True,
                )
                return SearchDecision("weather_location_clarification", source="explicit")
            return self._authorized_or_blocked(explicit, source="explicit")
        if source_urls:
            self._consent.clear()
            disposition = self._capability_disposition(
                implementation_available=self._source_retrieval_available
            )
            return SearchDecision(
                disposition,
                source="direct_url",
                source_urls=source_urls if disposition == "authorized" else (),
            )
        if consent_decision == "affirmative":
            assert confirmed_query is not None
            if self._weather_location_missing(confirmed_query):
                self._consent.propose_weather_location(
                    confirmed_query, conversation_id, directly_authorized=False,
                )
                return SearchDecision("weather_location_clarification", source="consent")
            return self._authorized_or_blocked(
                confirmed_query, source="consent"
            )
        if consent_decision == "negative":
            return SearchDecision("declined", source="consent")
        location, pending_weather = self._consent.resolve_weather_location(
            text, conversation_id
        )
        if pending_weather is not None:
            completed_query = pending_weather.query.rstrip("?.! ") + " in " + location
            if pending_weather.directly_authorized:
                return self._authorized_or_blocked(
                    completed_query, source="explicit"
                )
            disposition = self._capability_disposition()
            if disposition != "authorized":
                return SearchDecision(disposition, source="freshness")
            self._consent.propose(completed_query, conversation_id)
            return SearchDecision("proposal", source="freshness")
        if is_bare_search_request(text):
            self._consent.clear()
            return SearchDecision("clarification", source="bare")
        if should_propose_search(text):
            if self._weather_location_missing(text):
                self._consent.propose_weather_location(
                    text, conversation_id, directly_authorized=False,
                )
                return SearchDecision("weather_location_clarification", source="freshness")
            disposition = self._capability_disposition()
            if disposition != "authorized":
                self._consent.clear()
                return SearchDecision(disposition, source="freshness")
            self._consent.propose(text, conversation_id)
            return SearchDecision("proposal", source="freshness")
        return SearchDecision("normal")

    @staticmethod
    def _weather_location_missing(query: str) -> bool:
        return (
            search_category_for_query(query) == "weather"
            and weather_location_for_query(query) is None
        )

    def evaluate_explicit(self, text: str) -> SearchDecision:
        """Apply only direct-search rules for a non-interactive one-shot turn."""

        source_urls = explicit_source_urls(text)
        explicit = explicit_search_query(text)
        if explicit is None:
            if not source_urls:
                return SearchDecision("normal")
            disposition = self._capability_disposition(
                implementation_available=self._source_retrieval_available
            )
            return SearchDecision(
                disposition,
                source="direct_url",
                source_urls=source_urls if disposition == "authorized" else (),
            )
        if self._weather_location_missing(explicit):
            return SearchDecision("weather_location_clarification", source="explicit")
        return self._authorized_or_blocked(explicit, source="explicit")

    def propose_external_knowledge(
        self, text: str, *, conversation_id: str | None
    ) -> SearchDecision:
        disposition = self._capability_disposition()
        if disposition != "authorized":
            self._consent.clear()
            return SearchDecision(disposition, source="external_knowledge")
        try:
            self._consent.propose(text, conversation_id)
        except ValueError:
            self._consent.clear()
            return SearchDecision(
                "clarification", source="external_knowledge"
            )
        return SearchDecision("proposal", source="external_knowledge")

    def clear(self) -> None:
        self._consent.clear()

    def _authorized_or_blocked(
        self, query: str, *, source: SearchDecisionSource
    ) -> SearchDecision:
        disposition = self._capability_disposition()
        return SearchDecision(
            disposition,
            query if disposition == "authorized" else None,
            source,
        )

    def _capability_disposition(
        self,
        *,
        implementation_available: Callable[[], bool] | None = None,
    ) -> SearchDisposition:
        available = implementation_available or self._implementation_available
        if not available():
            return "unavailable"
        if self._capability_settings is None:
            return "authorized"
        try:
            capability = self._capability_settings.state().web_search
        except UserSettingsError:
            return "settings_failure"
        if not capability.administrator_permitted:
            return "unavailable"
        if not capability.user_enabled:
            return "disabled"
        return "authorized"
