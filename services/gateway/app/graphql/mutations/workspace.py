import re
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import strawberry
import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.types import WorkspaceAuthPayload, WorkspaceType
from core.models import Workspace, WorkspaceMember

logger = structlog.get_logger()

_SLUG_STRIP = re.compile(r"[^a-z0-9-]")
_SLUG_COLLAPSE = re.compile(r"-+")


def _derive_slug(name: str) -> str:
    raw = _SLUG_STRIP.sub("-", name.lower().strip())
    return _SLUG_COLLAPSE.sub("-", raw).strip("-")[:32]


def _unique_slug(base: str) -> str:
    slug = base
    suffix = 1
    while Workspace.objects.filter(slug=slug).exists():
        slug = f"{base[:29]}-{suffix}"
        suffix += 1
    return slug


def _issue_access_token(user_id: str, email: str, workspace_id: str, role: str) -> str:
    exp = datetime.now(tz=UTC) + timedelta(
        minutes=settings.GATEWAY_JWT_ACCESS_EXPIRY_MINUTES
    )
    return pyjwt.encode(
        {
            "user_id": user_id,
            "email": email,
            "workspace_id": workspace_id,
            "role": role,
            "iat": datetime.now(tz=UTC),
            "exp": exp,
        },
        settings.GATEWAY_JWT_SECRET,
        algorithm="HS256",
    )


def _issue_refresh_token(user_id: str, workspace_id: str) -> str:
    exp = datetime.now(tz=UTC) + timedelta(days=settings.GATEWAY_REFRESH_EXPIRY_DAYS)
    return pyjwt.encode(
        {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "type": "refresh",
            "iat": datetime.now(tz=UTC),
            "exp": exp,
        },
        settings.GATEWAY_REFRESH_SECRET,
        algorithm="HS256",
    )


def _get_response(info: Info) -> Any:
    ctx = info.context
    if isinstance(ctx, dict):
        return ctx.get("response")
    return getattr(ctx, "response", None)


def _get_request(info: Info) -> Any:
    """Return the request object from any Strawberry context layout."""
    ctx = info.context
    if isinstance(ctx, dict):
        return ctx.get("request")
    return getattr(ctx, "request", None)


def _set_refresh_cookie(info: Info, refresh_token: str) -> None:
    response = _get_response(info)
    if response is None:
        return
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
        path="/graphql",
        max_age=settings.GATEWAY_REFRESH_EXPIRY_DAYS * 86400,
    )


def _workspace_to_type(workspace: Workspace, role: str) -> WorkspaceType:
    return WorkspaceType(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        plan=workspace.plan,
        role=role,
        region=workspace.region,
        team_size=workspace.team_size,
        accent_color=workspace.accent_color,
        onboarded_at=(
            workspace.onboarded_at.isoformat() if workspace.onboarded_at else None
        ),
        created_at=workspace.created_at.isoformat(),
    )


def _create_workspace(
    info: Info,
    name: str,
    region: str = "eu",
    team_size: str = "solo",
    accent_color: str = "#6366f1",
) -> WorkspaceType:
    ctx = require_auth(info)
    name = name.strip()
    if not (2 <= len(name) <= 32):
        raise GraphQLError(
            "Workspace name must be 2–32 characters",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )
    try:
        region_choice = Workspace.Region(region)
    except ValueError:
        raise GraphQLError(
            f"Invalid region: {region}",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )
    try:
        team_size_choice = Workspace.TeamSize(team_size)
    except ValueError:
        raise GraphQLError(
            f"Invalid team_size: {team_size}",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )

    slug = _unique_slug(_derive_slug(name))
    workspace = Workspace.objects.create(
        owner_id=ctx.user_id,
        name=name,
        slug=slug,
        accent_color=accent_color,
        team_size=team_size_choice,
        region=region_choice,
    )
    WorkspaceMember.objects.create(
        workspace=workspace,
        user_id=ctx.user_id,
        role=WorkspaceMember.Role.ADMIN,
    )
    logger.info(
        "workspace_created",
        workspace_id=str(workspace.id),
        slug=slug,
        user_id=ctx.user_id,
    )
    return _workspace_to_type(workspace, WorkspaceMember.Role.ADMIN)


def _select_workspace(info: Info, workspace_id: str) -> WorkspaceAuthPayload:
    ctx = require_auth(info)
    try:
        member = WorkspaceMember.objects.select_related("workspace").get(
            workspace_id=workspace_id,
            user_id=ctx.user_id,
        )
    except WorkspaceMember.DoesNotExist:
        raise GraphQLError(
            "You are not a member of this workspace",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    ws = member.workspace
    access_token = _issue_access_token(
        user_id=ctx.user_id,
        email=ctx.email,
        workspace_id=str(ws.id),
        role=member.role,
    )
    _set_refresh_cookie(info, _issue_refresh_token(ctx.user_id, str(ws.id)))
    logger.info(
        "workspace_selected",
        workspace_id=workspace_id,
        user_id=ctx.user_id,
        role=member.role,
    )
    return WorkspaceAuthPayload(
        token=access_token,
        user_id=ctx.user_id,
        email=ctx.email,
        workspace_id=str(ws.id),
        role=member.role,
    )


def _refresh_token(info: Info) -> WorkspaceAuthPayload:
    req = _get_request(info)
    # Django: request.COOKIES  |  Starlette: request.cookies
    cookies = getattr(req, "COOKIES", None) or getattr(req, "cookies", {})
    cookie = cookies.get("refresh_token")
    if not cookie:
        raise GraphQLError(
            "No refresh token cookie",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_MISSING),
        )

    try:
        payload = pyjwt.decode(
            cookie, settings.GATEWAY_REFRESH_SECRET, algorithms=["HS256"]
        )
    except pyjwt.ExpiredSignatureError:
        raise GraphQLError(
            "Refresh token expired",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_INVALID),
        )
    except pyjwt.PyJWTError:
        raise GraphQLError(
            "Invalid refresh token",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_INVALID),
        )

    if payload.get("type") != "refresh":
        raise GraphQLError(
            "Invalid token type",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_INVALID),
        )

    user_id: str = payload["user_id"]
    workspace_id: str = payload["workspace_id"]

    try:
        member = WorkspaceMember.objects.select_related("workspace").get(
            workspace_id=workspace_id, user_id=user_id
        )
    except WorkspaceMember.DoesNotExist:
        raise GraphQLError(
            "Workspace membership revoked",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    access_token = _issue_access_token(
        user_id=user_id,
        email="",
        workspace_id=workspace_id,
        role=member.role,
    )
    _set_refresh_cookie(info, _issue_refresh_token(user_id, workspace_id))

    return WorkspaceAuthPayload(
        token=access_token,
        user_id=user_id,
        email="",
        workspace_id=workspace_id,
        role=member.role,
    )


def _update_workspace(
    info: Info,
    workspace_id: str,
    name: str | None = None,
    accent_color: str | None = None,
    team_size: str | None = None,
) -> WorkspaceType:
    ctx = require_auth(info)
    if ctx.workspace_id != workspace_id or ctx.role != WorkspaceMember.Role.ADMIN:
        raise GraphQLError(
            "Admin access required for this workspace",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError(
            "Workspace not found",
            extensions=graphql_error_extensions(ErrorCode.NOT_FOUND),
        )

    if name is not None:
        name = name.strip()
        if not (2 <= len(name) <= 32):
            raise GraphQLError(
                "Workspace name must be 2–32 characters",
                extensions=graphql_error_extensions(ErrorCode.VALIDATION),
            )
        workspace.name = name
    if accent_color is not None:
        workspace.accent_color = accent_color
    if team_size is not None:
        try:
            workspace.team_size = Workspace.TeamSize(team_size)
        except ValueError:
            raise GraphQLError(
                f"Invalid team_size: {team_size}",
                extensions=graphql_error_extensions(ErrorCode.VALIDATION),
            )
    workspace.save()
    logger.info("workspace_updated", workspace_id=workspace_id, user_id=ctx.user_id)
    return _workspace_to_type(workspace, ctx.role)


@strawberry.mutation
async def create_workspace(
    info: Info,
    name: str,
    region: str = "eu",
    team_size: str = "solo",
    accent_color: str = "#6366f1",
) -> WorkspaceType:
    return await sync_to_async(_create_workspace)(
        info, name, region, team_size, accent_color
    )


@strawberry.mutation
async def select_workspace(info: Info, workspace_id: str) -> WorkspaceAuthPayload:
    return await sync_to_async(_select_workspace)(info, workspace_id)


@strawberry.mutation
async def refresh_token(info: Info) -> WorkspaceAuthPayload:
    return await sync_to_async(_refresh_token)(info)


@strawberry.mutation
async def update_workspace(
    info: Info,
    workspace_id: str,
    name: str | None = None,
    accent_color: str | None = None,
    team_size: str | None = None,
) -> WorkspaceType:
    return await sync_to_async(_update_workspace)(
        info, workspace_id, name, accent_color, team_size
    )
