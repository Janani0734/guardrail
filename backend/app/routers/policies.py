import uuid

from fastapi import APIRouter, Query, Response, status

from app.models.enums import Decision, PolicyType
from app.routers.deps import Admin, RedisDep, SessionDep, Viewer
from app.schemas.common import Page
from app.schemas.policies import PolicyCreate, PolicyOut, PolicyUpdate, SimulateRequest, SimulateResponse
from app.services.cache import bump_analytics_version
from app.services.policy_service import PolicyService

router = APIRouter(prefix="/v1/policies", tags=["policies"])


@router.get("", response_model=Page[PolicyOut])
async def list_policies(
    p: Viewer, session: SessionDep, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    policy_type: PolicyType | None = None, effect: Decision | None = None, is_active: bool | None = None,
    search: str | None = Query(None, max_length=80),
):
    items, total = await PolicyService(session).policies.list(
        p.org_id, page, page_size, policy_type, effect, is_active, search)
    return Page.build([PolicyOut.model_validate(x) for x in items], total, page, page_size)


@router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(data: PolicyCreate, p: Admin, session: SessionDep):
    return await PolicyService(session).create(p, data)


@router.post("/simulate", response_model=SimulateResponse)
async def simulate(data: SimulateRequest, p: Viewer, session: SessionDep):
    return await PolicyService(session).simulate(p, data)


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(policy_id: uuid.UUID, p: Viewer, session: SessionDep):
    return await PolicyService(session).get(p, policy_id)


@router.patch("/{policy_id}", response_model=PolicyOut)
async def update_policy(policy_id: uuid.UUID, data: PolicyUpdate, p: Admin, session: SessionDep):
    return await PolicyService(session).update(p, policy_id, data)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, p: Admin, session: SessionDep, redis: RedisDep):
    await PolicyService(session).delete(p, policy_id)
    await bump_analytics_version(redis, p.org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
