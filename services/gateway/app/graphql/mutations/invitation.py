from datetime import timedelta

import strawberry
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone as django_tz
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.mutations.workspace import (
    _issue_access_token,
    _issue_refresh_token,
    _set_refresh_cookie,
)
from app.graphql.types import WorkspaceAuthPayload
from core.models import Invitation, Workspace, WorkspaceMember

logger = structlog.get_logger()

_INVITE_EXPIRY_DAYS = 7

_ROLE_PRIORITY = {
    WorkspaceMember.Role.VIEWER: 1,
    WorkspaceMember.Role.MEMBER: 2,
    WorkspaceMember.Role.ADMIN: 3,
}


@strawberry.type
class InvitationPayload:
    id: str
    token: str
    email: str
    role: str
    status: str
    expires_at: str
    created_at: str


def _invite_member(
    info: Info, workspace_id: str, email: str, role: str = "member"
) -> InvitationPayload:
    ctx = require_auth(info)

    try:
        member = WorkspaceMember.objects.get(
            workspace_id=workspace_id, user_id=ctx.user_id
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionError("Access denied to workspace")

    if member.role != WorkspaceMember.Role.ADMIN:
        raise PermissionError("Only admins can invite members")

    try:
        role_choice = WorkspaceMember.Role(role)
    except ValueError:
        raise GraphQLError(
            f"Invalid role: {role}",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError("Workspace not found")

    # Revoke any existing pending invite for the same email+workspace
    Invitation.objects.filter(
        workspace=workspace,
        email=email,
        status=Invitation.Status.PENDING,
    ).update(status=Invitation.Status.REVOKED)

    expires_at = django_tz.now() + timedelta(days=_INVITE_EXPIRY_DAYS)
    invite = Invitation.objects.create(
        workspace=workspace,
        email=email,
        role=role_choice,
        invited_by_user_id=ctx.user_id,
        expires_at=expires_at,
    )

    logger.info(
        "invitation_sent",
        invitation_id=str(invite.id),
        workspace_id=workspace_id,
        email=email,
        role=role,
        user_id=ctx.user_id,
    )

    return InvitationPayload(
        id=str(invite.id),
        token=str(invite.token),
        email=invite.email,
        role=invite.role,
        status=invite.status,
        expires_at=expires_at.isoformat(),
        created_at=invite.created_at.isoformat(),
    )


def _revoke_invitation(info: Info, invitation_id: str) -> bool:
    ctx = require_auth(info)

    try:
        invite = Invitation.objects.select_related("workspace").get(id=invitation_id)
    except Invitation.DoesNotExist:
        raise GraphQLError("Invitation not found")

    try:
        WorkspaceMember.objects.get(
            workspace=invite.workspace,
            user_id=ctx.user_id,
            role=WorkspaceMember.Role.ADMIN,
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionError("Only admins can revoke invitations")

    invite.status = Invitation.Status.REVOKED
    invite.save(update_fields=["status"])
    logger.info("invitation_revoked", invitation_id=invitation_id, user_id=ctx.user_id)
    return True


def _accept_invitation(info: Info, token: str) -> WorkspaceAuthPayload:
    """Accept an invitation by token.

    If the user is already authenticated (workspace or user JWT in header), we use that
    user_id directly. If no auth header is present, returns an error — the frontend
    must ensure the user is registered/logged in before calling this mutation.
    """
    ctx = require_auth(info)

    try:
        invite = Invitation.objects.select_related("workspace").get(token=token)
    except Invitation.DoesNotExist:
        raise GraphQLError("Invitation not found or already used")

    if invite.status != Invitation.Status.PENDING:
        raise GraphQLError(f"Invitation is {invite.status}")

    if invite.expires_at < django_tz.now():
        invite.status = Invitation.Status.EXPIRED
        invite.save(update_fields=["status"])
        raise GraphQLError("Invitation expired")

    # Add the user as a workspace member, or upgrade their role — never downgrade.
    member, created = WorkspaceMember.objects.get_or_create(
        workspace=invite.workspace,
        user_id=ctx.user_id,
        defaults={"role": invite.role},
    )
    if not created and _ROLE_PRIORITY.get(invite.role, 0) > _ROLE_PRIORITY.get(
        member.role, 0
    ):
        member.role = invite.role
        member.save(update_fields=["role"])
    invite.status = Invitation.Status.ACCEPTED
    invite.save(update_fields=["status"])

    ws = invite.workspace
    access_token = _issue_access_token(
        user_id=ctx.user_id,
        email=ctx.email,
        workspace_id=str(ws.id),
        role=invite.role,
    )
    _set_refresh_cookie(info, _issue_refresh_token(ctx.user_id, str(ws.id)))

    logger.info(
        "invitation_accepted",
        invitation_id=str(invite.id),
        workspace_id=str(ws.id),
        user_id=ctx.user_id,
    )

    return WorkspaceAuthPayload(
        token=access_token,
        user_id=ctx.user_id,
        email=ctx.email,
        workspace_id=str(ws.id),
        role=invite.role,
    )


def _generate_invite_link(info: Info, workspace_id: str) -> InvitationPayload:
    ctx = require_auth(info)

    try:
        WorkspaceMember.objects.get(
            workspace_id=workspace_id,
            user_id=ctx.user_id,
            role=WorkspaceMember.Role.ADMIN,
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionError("Only admins can generate invite links")

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError("Workspace not found")

    expires_at = django_tz.now() + timedelta(days=_INVITE_EXPIRY_DAYS)
    invite = Invitation.objects.create(
        workspace=workspace,
        email="",  # open link — no specific email target
        role=WorkspaceMember.Role.MEMBER,
        invited_by_user_id=ctx.user_id,
        expires_at=expires_at,
    )

    return InvitationPayload(
        id=str(invite.id),
        token=str(invite.token),
        email="",
        role=invite.role,
        status=invite.status,
        expires_at=expires_at.isoformat(),
        created_at=invite.created_at.isoformat(),
    )


@strawberry.mutation
async def invite_member(
    info: Info, workspace_id: str, email: str, role: str = "member"
) -> InvitationPayload:
    return await sync_to_async(_invite_member)(info, workspace_id, email, role)


@strawberry.mutation
async def revoke_invitation(info: Info, invitation_id: str) -> bool:
    return await sync_to_async(_revoke_invitation)(info, invitation_id)


@strawberry.mutation
async def accept_invitation(info: Info, token: str) -> WorkspaceAuthPayload:
    return await sync_to_async(_accept_invitation)(info, token)


@strawberry.mutation
async def generate_invite_link(info: Info, workspace_id: str) -> InvitationPayload:
    return await sync_to_async(_generate_invite_link)(info, workspace_id)
