import uuid
from dataclasses import dataclass

from app.models.enums import Role

ROLE_RANK = {Role.VIEWER: 1, Role.MANAGER: 2, Role.ADMIN: 3}


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    full_name: str
    org_id: uuid.UUID
    role: Role

    def at_least(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]
