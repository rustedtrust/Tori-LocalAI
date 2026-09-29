"""Application-owned clocks and deterministic local civil-time resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimeContextError(ValueError):
    """Raised when authoritative scheduling time cannot be established."""


class NonexistentCivilTimeError(TimeContextError):
    """Raised for a local wall time skipped by a UTC-offset transition."""


class AmbiguousCivilTimeError(TimeContextError):
    """Raised for a local wall time that occurs twice."""


Clock = Callable[[], datetime]


_WEEKDAY_QUESTION = re.compile(
    r"(?i)^what\s+(?:day\s+of\s+the\s+week|weekday|day)\s+"
    r"(?:is\s+it|is)(?:\s+today)?[?!.]*$"
)


def utc_now() -> datetime:
    """Return the production aware UTC instant."""

    return datetime.now(timezone.utc)


class FakeClock:
    """A controllable aware clock for tests and deterministic scheduling."""

    def __init__(self, value: datetime) -> None:
        self._value = _aware_utc(value)

    def __call__(self) -> datetime:
        return self._value

    def set(self, value: datetime) -> None:
        self._value = _aware_utc(value)

    def advance(self, delta: timedelta) -> datetime:
        if not isinstance(delta, timedelta):
            raise TypeError("Fake clock advancement requires a timedelta.")
        self._value += delta
        return self._value


@dataclass(frozen=True, slots=True)
class TimeContext:
    """One captured authoritative instant represented in UTC and local time."""

    captured_utc: datetime
    timezone_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_utc", _aware_utc(self.captured_utc))
        validate_timezone_name(self.timezone_name)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def local_datetime(self) -> datetime:
        return self.captured_utc.astimezone(self.zone)

    @property
    def local_date(self) -> date:
        return self.local_datetime.date()

    @property
    def utc_offset(self) -> timedelta:
        offset = self.local_datetime.utcoffset()
        assert offset is not None
        return offset

    @property
    def is_dst(self) -> bool:
        delta = self.local_datetime.dst()
        return bool(delta and delta != timedelta(0))

    def elapsed(self, delta: timedelta) -> datetime:
        """Resolve an elapsed duration from the captured instant."""

        if not isinstance(delta, timedelta) or delta <= timedelta(0):
            raise TimeContextError("Elapsed scheduling duration must be positive.")
        return self.captured_utc + delta

    def civil_date(self, relation: str, *, weekday: int | None = None) -> date:
        """Resolve today, tomorrow, or the next named weekday locally."""

        if relation == "today":
            return self.local_date
        if relation == "tomorrow":
            return self.local_date + timedelta(days=1)
        if relation == "weekday" and isinstance(weekday, int) and 0 <= weekday <= 6:
            distance = (weekday - self.local_date.weekday()) % 7
            return self.local_date + timedelta(days=distance or 7)
        raise TimeContextError("The relative civil date is invalid.")

    def resolve_civil(
        self,
        local_date: date,
        local_time: time,
        *,
        fold: int | None = None,
    ) -> datetime:
        """Resolve one local wall time, rejecting DST gaps and overlaps."""

        if not isinstance(local_date, date) or not isinstance(local_time, time):
            raise TimeContextError("A local date and time are required.")
        if local_time.tzinfo is not None:
            raise TimeContextError("Civil times must not contain a timezone.")
        naive = datetime.combine(local_date, local_time.replace(fold=0))
        candidates: list[datetime] = []
        for occurrence in (0, 1):
            aware = naive.replace(tzinfo=self.zone, fold=occurrence)
            instant = aware.astimezone(timezone.utc)
            round_trip = instant.astimezone(self.zone)
            if round_trip.replace(tzinfo=None) == naive and round_trip.fold == occurrence:
                candidates.append(instant)
        unique = tuple(dict.fromkeys(candidates))
        if not unique:
            raise NonexistentCivilTimeError(
                "That local time does not exist because the clock moves forward."
            )
        if len(unique) == 2:
            if fold not in {0, 1}:
                raise AmbiguousCivilTimeError(
                    "That local time occurs twice because the clock moves backward."
                )
            return unique[fold]
        return unique[0]

    def provider_context(self) -> str:
        """Return bounded application-authored time context for ordinary turns."""

        local = self.local_datetime
        offset = local.strftime("%z")
        rendered_offset = f"{offset[:3]}:{offset[3:]}"
        return (
            "Authoritative application time (do not replace or infer): "
            f"local={local.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"timezone={self.timezone_name}, UTC offset={rendered_offset}, "
            f"UTC={format_utc_timestamp(self.captured_utc)}."
        )


def capture_time_context(clock: Clock, timezone_name: str) -> TimeContext:
    """Capture one clock reading for a complete application turn."""

    return TimeContext(clock(), validate_timezone_name(timezone_name))


def current_weekday_answer(text: str, context: TimeContext) -> str | None:
    """Answer only narrowly phrased current-weekday questions from Tori time."""

    normalized = " ".join(text.strip().split())
    if _WEEKDAY_QUESTION.fullmatch(normalized) is None:
        return None
    return f"Today is {context.local_date.strftime('%A')}."


def discover_timezone(
    configured: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    localtime_path: Path = Path("/etc/localtime"),
    timezone_path: Path = Path("/etc/timezone"),
) -> str:
    """Resolve config, environment, then a validated host IANA zone."""

    if configured is not None:
        return validate_timezone_name(configured)
    environment = os.environ if environ is None else environ
    supplied = environment.get("TORI_TIMEZONE")
    if supplied is not None:
        return validate_timezone_name(supplied)
    candidates: list[str] = []
    try:
        target = os.readlink(localtime_path)
        marker = "/zoneinfo/"
        if marker in target:
            candidates.append(target.split(marker, 1)[1])
    except OSError:
        pass
    try:
        value = timezone_path.read_text(encoding="utf-8").strip()
        if value:
            candidates.append(value)
    except (OSError, UnicodeError):
        pass
    for candidate in candidates:
        try:
            return validate_timezone_name(candidate)
        except TimeContextError:
            continue
    raise TimeContextError(
        "Tori could not determine an IANA timezone; set [time] timezone or TORI_TIMEZONE."
    )


def validate_timezone_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "/" not in value
        or value.startswith("/")
        or ".." in value.split("/")
        or len(value) > 255
    ):
        raise TimeContextError("Timezone must be an IANA Area/Location name.")
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimeContextError("Timezone must be a recognized IANA name.") from exc
    if zone.key != value:
        raise TimeContextError("Timezone must be a canonical IANA name.")
    return value


def format_utc_timestamp(value: datetime) -> str:
    return _aware_utc(value).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TimeContextError("Timestamp must be a UTC Z timestamp.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise TimeContextError("Timestamp must be a UTC Z timestamp.") from exc
    if format_utc_timestamp(parsed) != value:
        raise TimeContextError("Timestamp must be a UTC Z timestamp.")
    return parsed


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TimeContextError("Clock values must be timezone-aware datetimes.")
    return value.astimezone(timezone.utc)
