from fastapi import APIRouter, status

from app.core.exceptions import Unauthorized
from app.repositories.identity import OrganizationRepository
from app.routers.deps import PrincipalDep, RedisDep, SessionDep
from app.schemas.auth import (
    AuthResponse, LoginRequest, LogoutRequest, MeResponse, OrganizationOut, RefreshRequest, RegisterRequest, UserOut,
)
from app.schemas.common import Message
from app.services.auth_service import AuthService

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, session: SessionDep, redis: RedisDep):
    return await AuthService(session, redis).register(data)


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, session: SessionDep, redis: RedisDep):
    return await AuthService(session, redis).login(data)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(data: RefreshRequest, session: SessionDep, redis: RedisDep):
    return await AuthService(session, redis).refresh(data.refresh_token)


@router.post("/logout", response_model=Message)
async def logout(data: LogoutRequest, session: SessionDep, redis: RedisDep):
    await AuthService(session, redis).logout(data.refresh_token)
    return Message(message="Logged out")


@router.get("/me", response_model=MeResponse)
async def me(principal: PrincipalDep, session: SessionDep):
    from app.repositories.identity import UserRepository

    user = await UserRepository(session).get(principal.user_id)
    org = await OrganizationRepository(session).get(principal.org_id)
    if not user or not org:
        raise Unauthorized("Invalid token", code="INVALID_TOKEN")
    return MeResponse(user=UserOut.model_validate(user), organization=OrganizationOut.model_validate(org),
                      role=principal.role)
