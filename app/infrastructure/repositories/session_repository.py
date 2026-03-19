from app.domain.models.session import ResearchSession


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._storage: dict[str, ResearchSession] = {}

    def save(self, session: ResearchSession) -> None:
        self._storage[session.session_id] = session

    def get(self, session_id: str) -> ResearchSession | None:
        return self._storage.get(session_id)

