"""Plans: drafted sequences of steps the user can review before anything runs.

POST /v1/plans drafts a plan for a goal with the configured model, optionally using an
owned conversation's recent turns, and stores it as a draft. Nothing executes: running
approved plans arrives with the workflow engine (phase 4). DELETE discards a draft.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai.errors import AiError
from app.ai.providers.base import Message
from app.api.v1.pagination import Limit, Offset, PageMeta
from app.conversations.store import ConversationNotFoundError, ConversationStore
from app.core.auth import CurrentPrincipal, Principal
from app.core.errors import ApiError
from app.db.session import get_session
from app.memory import retrieval
from app.memory.indexing import embed_query
from app.orchestration import planner
from app.orchestration.plan_store import PlanNotFoundError, PlanStore
from greenloop_contracts import Plan
from greenloop_contracts.base import Identifier
from greenloop_contracts.plan import Goal

router = APIRouter(prefix="/plans", tags=["plans"])
DbSession = Annotated[Session, Depends(get_session)]
PlanId = Annotated[str, Path(max_length=128)]
HISTORY_MESSAGES = 20


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Goal
    conversation_id: Identifier | None = None


class PlanPage(BaseModel):
    data: list[Plan]
    meta: PageMeta


def _not_found() -> ApiError:
    return ApiError(404, "PLAN_NOT_FOUND", "Plan not found.")


def _store(request: Request, session: DbSession, principal: CurrentPrincipal) -> PlanStore:
    return PlanStore(session, principal.principal_id, request.state.correlation_id)


Store = Annotated[PlanStore, Depends(_store)]


@router.post("", status_code=201)
async def create_plan(body: PlanCreate, request: Request, principal: CurrentPrincipal) -> Plan:
    state = request.app.state
    if state.session_factory is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not configured.")
    try:
        provider = state.provider_registry.get(None)
    except AiError as err:
        raise err.to_api_error() from None
    drafting: set[str] = state.plans_drafting
    if principal.principal_id in drafting:
        raise ApiError(
            409, "PLAN_DRAFT_BUSY", "A plan is already being drafted. Wait for it to finish."
        )
    drafting.add(principal.principal_id)
    try:
        query_vector = await embed_query(state.embedder, body.goal)
        try:
            model_request = await asyncio.to_thread(
                _prepare, request, principal, body, query_vector
            )
        except ConversationNotFoundError:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found.") from None
        try:
            async with asyncio.timeout(state.settings.ai_timeout_seconds):
                reply, done = await planner.generate(provider, model_request)
            # Model output is redacted before it is stored, as chat replies are.
            steps = planner.parse_plan_steps(state.redactor.redact(reply))
        except TimeoutError:
            raise AiError("timeout").to_api_error() from None
        except AiError as err:
            raise err.to_api_error() from None
        except planner.PlanDraftError:
            raise ApiError(
                502, "PLAN_DRAFT_INVALID", "The model did not return a usable plan. Try again."
            ) from None
        usage = {
            "provider": provider.config.name,
            "model": provider.config.model,
            "input_tokens": done.input_tokens,
            "output_tokens": done.output_tokens,
        }
        return await asyncio.to_thread(_store_plan, request, principal, body, steps, usage)
    finally:
        drafting.discard(principal.principal_id)


def _prepare(request: Request, principal: Principal, body: PlanCreate, query_vector):
    state = request.app.state
    correlation_id = request.state.correlation_id
    with state.session_factory() as session:
        history: list[Message] = []
        if body.conversation_id is not None:
            conversations = ConversationStore(session, principal.principal_id, correlation_id)
            history = [
                Message(role=row.role, content=row.content)
                for row in conversations.history(body.conversation_id, HISTORY_MESSAGES)
            ]
        records = retrieval.retrieve(
            session,
            principal.principal_id,
            body.goal,
            limit=state.settings.ai_memory_record_limit,
            correlation_id=correlation_id,
            query_vector=query_vector,
            model=state.embedder.model if state.embedder is not None else None,
        )
        session.rollback()
    model_request, _ = planner.build_planner_request(
        records,
        body.goal,
        history,
        principal_id=principal.principal_id,
        redactor=state.redactor,
    )
    return model_request


def _store_plan(
    request: Request, principal: Principal, body: PlanCreate, steps, usage: dict
) -> Plan:
    with request.app.state.session_factory() as session:
        plan = PlanStore(session, principal.principal_id, request.state.correlation_id).create(
            request.app.state.redactor.redact(body.goal), steps, body.conversation_id, usage
        )
        session.commit()
    return plan


@router.get("")
def list_plans(store: Store, limit: Limit = 50, offset: Offset = 0) -> PlanPage:
    plans, total = store.list(limit=limit, offset=offset)
    return PlanPage(data=plans, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.get("/{plan_id}")
def get_plan(plan_id: PlanId, store: Store) -> Plan:
    try:
        return store.get(plan_id)
    except PlanNotFoundError:
        raise _not_found() from None


@router.delete("/{plan_id}", status_code=204)
def discard_plan(plan_id: PlanId, store: Store, session: DbSession) -> Response:
    try:
        store.discard(plan_id)
    except PlanNotFoundError:
        raise _not_found() from None
    session.commit()
    return Response(status_code=204)
