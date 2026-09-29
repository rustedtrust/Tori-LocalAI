"""Presentation-neutral Tori planning use cases."""

from __future__ import annotations

from datetime import datetime

from .planning import (
    Event, PlanningCollection, PlanningPort, PlanningStatus, Task, completed_task,
)


class PlanningService:
    """Coordinate planning operations after a Tori-owned authority decision."""

    def __init__(self, port: PlanningPort) -> None:
        self._port = port

    def status(self) -> PlanningStatus:
        return self._port.status()

    def list_collections(self) -> tuple[PlanningCollection, ...]:
        return self._port.list_collections()

    def create_task(self, task: Task) -> Task:
        return self._port.create_task(task)

    def get_task(self, collection_id: str, uid: str) -> Task:
        return self._port.get_task(collection_id, uid)

    def list_tasks(self, collection_id: str) -> tuple[Task, ...]:
        return self._port.list_tasks(collection_id)

    def update_task(self, task: Task, *, expected_revision: str) -> Task:
        return self._port.update_task(task, expected_revision=expected_revision)

    def complete_task(
        self, task: Task, *, when: datetime, expected_revision: str
    ) -> Task:
        return self._port.update_task(
            completed_task(task, when), expected_revision=expected_revision
        )

    def delete_task(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None:
        self._port.delete_task(
            collection_id, uid, expected_revision=expected_revision
        )

    def create_event(self, event: Event) -> Event:
        return self._port.create_event(event)

    def get_event(self, collection_id: str, uid: str) -> Event:
        return self._port.get_event(collection_id, uid)

    def list_events(self, collection_id: str) -> tuple[Event, ...]:
        return self._port.list_events(collection_id)

    def update_event(self, event: Event, *, expected_revision: str) -> Event:
        return self._port.update_event(event, expected_revision=expected_revision)

    def delete_event(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None:
        self._port.delete_event(
            collection_id, uid, expected_revision=expected_revision
        )
