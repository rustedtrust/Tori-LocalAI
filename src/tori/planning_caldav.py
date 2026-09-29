"""CalDAV adapter for Tori's replaceable PlanningPort."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlparse

from caldav import DAVClient
from caldav.elements import dav
from caldav.lib import error as caldav_error

from .planning import (
    Event, PlanningAvailability, PlanningCollection, PlanningConflictError,
    PlanningDataError, PlanningError, PlanningNotFoundError, PlanningStatus,
    PlanningUnavailableError, Task,
)
from .planning_icalendar import (
    deserialize_event, deserialize_task, serialize_event, serialize_task,
)


_T = TypeVar("_T")


class CalDAVPlanningAdapter:
    """Translate Tori planning values through a standard CalDAV client."""

    def __init__(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
        ):
            raise PlanningDataError(
                "The foundation CalDAV endpoint must be a numeric IPv4 loopback URL."
            )
        if username is None and password is not None:
            raise PlanningDataError("A CalDAV password requires a username.")
        if not 0 < timeout_seconds <= 30:
            raise PlanningDataError("CalDAV timeout must be at most 30 seconds.")
        self._client = DAVClient(
            url.rstrip("/") + "/",
            username=username,
            password=(password if password is not None else "") if username else None,
            timeout=max(1, int(timeout_seconds)),
            require_tls=parsed.scheme == "https",
        )

    def close(self) -> None:
        self._client.close()

    def status(self) -> PlanningStatus:
        try:
            available = bool(self._client.check_cdav_support())
            if available:
                self._client.principal().calendars()
        except Exception:
            return PlanningStatus(
                PlanningAvailability.UNAVAILABLE,
                "Planning is configured but unavailable.",
            )
        if not available:
            return PlanningStatus(
                PlanningAvailability.UNAVAILABLE,
                "Planning is configured but unavailable.",
            )
        return PlanningStatus(
            PlanningAvailability.AVAILABLE, "Planning is available."
        )

    def list_collections(self) -> tuple[PlanningCollection, ...]:
        def operation() -> tuple[PlanningCollection, ...]:
            result = []
            for calendar in self._client.principal().calendars():
                components = set(calendar.get_supported_components())
                result.append(PlanningCollection(
                    identifier=str(calendar.url),
                    name=str(calendar.get_display_name() or "Planning"),
                    supports_tasks="VTODO" in components,
                    supports_events="VEVENT" in components,
                ))
            return tuple(sorted(result, key=lambda item: item.identifier))
        return self._remote(operation)

    def create_task(self, task: Task) -> Task:
        def operation() -> Task:
            calendar = self._calendar(task.collection_id)
            calendar.save_todo(ical=serialize_task(task), no_overwrite=True)
            return self._read_task(calendar, task.collection_id, task.uid)
        return self._remote(operation)

    def get_task(self, collection_id: str, uid: str) -> Task:
        return self._remote(
            lambda: self._read_task(self._calendar(collection_id), collection_id, uid)
        )

    def list_tasks(self, collection_id: str) -> tuple[Task, ...]:
        def operation() -> tuple[Task, ...]:
            calendar = self._calendar(collection_id)
            values = [
                deserialize_task(
                    item.data,
                    collection_id=collection_id,
                    revision=self._etag(item),
                )
                for item in calendar.todos(include_completed=True)
            ]
            return tuple(sorted(values, key=lambda item: item.uid))
        return self._remote(operation)

    def update_task(self, task: Task, *, expected_revision: str) -> Task:
        def operation() -> Task:
            calendar = self._calendar(task.collection_id)
            item = calendar.todo_by_uid(task.uid)
            self._conditional_put(item, serialize_task(task), expected_revision)
            return self._read_task(calendar, task.collection_id, task.uid)
        return self._remote(operation)

    def delete_task(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None:
        self._remote(lambda: self._conditional_delete(
            self._calendar(collection_id).todo_by_uid(uid), expected_revision
        ))

    def create_event(self, event: Event) -> Event:
        def operation() -> Event:
            calendar = self._calendar(event.collection_id)
            calendar.save_event(ical=serialize_event(event), no_overwrite=True)
            return self._read_event(calendar, event.collection_id, event.uid)
        return self._remote(operation)

    def get_event(self, collection_id: str, uid: str) -> Event:
        return self._remote(
            lambda: self._read_event(self._calendar(collection_id), collection_id, uid)
        )

    def list_events(self, collection_id: str) -> tuple[Event, ...]:
        def operation() -> tuple[Event, ...]:
            calendar = self._calendar(collection_id)
            values = [
                deserialize_event(
                    item.data,
                    collection_id=collection_id,
                    revision=self._etag(item),
                )
                for item in calendar.events()
            ]
            return tuple(sorted(values, key=lambda item: item.uid))
        return self._remote(operation)

    def update_event(self, event: Event, *, expected_revision: str) -> Event:
        def operation() -> Event:
            calendar = self._calendar(event.collection_id)
            item = calendar.event_by_uid(event.uid)
            self._conditional_put(item, serialize_event(event), expected_revision)
            return self._read_event(calendar, event.collection_id, event.uid)
        return self._remote(operation)

    def delete_event(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None:
        self._remote(lambda: self._conditional_delete(
            self._calendar(collection_id).event_by_uid(uid), expected_revision
        ))

    def _calendar(self, collection_id: str):
        if not isinstance(collection_id, str) or not collection_id:
            raise PlanningDataError("Planning collection identity is invalid.")
        return self._client.calendar(url=collection_id)

    def _read_task(self, calendar, collection_id: str, uid: str) -> Task:
        item = calendar.todo_by_uid(uid)
        return deserialize_task(
            item.data, collection_id=collection_id, revision=self._etag(item)
        )

    def _read_event(self, calendar, collection_id: str, uid: str) -> Event:
        item = calendar.event_by_uid(uid)
        return deserialize_event(
            item.data, collection_id=collection_id, revision=self._etag(item)
        )

    @staticmethod
    def _etag(item) -> str:
        value = item.get_property(dav.GetEtag())
        if not isinstance(value, str) or not value:
            raise PlanningDataError("The backend did not provide an object revision.")
        return value

    def _conditional_put(self, item, data: str, expected_revision: str) -> None:
        current = self._etag(item)
        if current != expected_revision:
            raise PlanningConflictError("The planning object changed; reload it first.")
        response = self._client.put(
            str(item.url),
            data,
            {"Content-Type": "text/calendar; charset=utf-8", "If-Match": expected_revision},
        )
        if response.status == 412:
            raise PlanningConflictError("The planning object changed; reload it first.")
        if response.status not in {200, 201, 204}:
            raise PlanningUnavailableError("The planning update did not complete.")

    def _conditional_delete(self, item, expected_revision: str) -> None:
        current = self._etag(item)
        if current != expected_revision:
            raise PlanningConflictError("The planning object changed; reload it first.")
        response = self._client.request(
            str(item.url), "DELETE", headers={"If-Match": expected_revision}
        )
        if response.status == 412:
            raise PlanningConflictError("The planning object changed; reload it first.")
        if response.status not in {200, 204}:
            raise PlanningUnavailableError("The planning deletion did not complete.")

    @staticmethod
    def _remote(operation: Callable[[], _T]) -> _T:
        try:
            return operation()
        except PlanningError:
            raise
        except caldav_error.NotFoundError as exc:
            raise PlanningNotFoundError("The planning object was not found.") from exc
        except caldav_error.ConsistencyError as exc:
            raise PlanningConflictError("The planning object already exists.") from exc
        except Exception as exc:
            raise PlanningUnavailableError(
                "The configured planning backend could not complete the request."
            ) from exc
