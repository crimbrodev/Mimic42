from __future__ import annotations

from uuid import UUID

from mimic42.api.auth import CurrentUser

AUTH_HEADERS = {"Authorization": "Bearer test-token"}


class FakeAuthVerifier:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        self.tokens: list[str] = []

    async def verify(self, token: str) -> CurrentUser:
        self.tokens.append(token)
        return CurrentUser(user_id=self.user_id)
