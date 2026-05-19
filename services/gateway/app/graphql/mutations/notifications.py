import strawberry
import structlog
from asgiref.sync import sync_to_async
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from core.models import (
    AlertRule,
    NotificationChannel,
    QuietHours,
    Workspace,
    WorkspaceMember,
)

logger = structlog.get_logger()


@strawberry.type
class AlertRuleType:
    id: str
    workspace_id: str
    name: str
    event_type: str
    enabled: bool
    created_at: str


@strawberry.type
class ChannelPayload:
    id: str
    workspace_id: str
    type: str
    enabled: bool
    created_at: str


@strawberry.type
class QuietHoursType:
    id: str
    workspace_id: str
    enabled: bool
    start_time: str
    end_time: str
    timezone: str
    weekdays_only: bool


def _require_admin(user_id: str, workspace_id: str) -> None:
    try:
        WorkspaceMember.objects.get(
            workspace_id=workspace_id,
            user_id=user_id,
            role=WorkspaceMember.Role.ADMIN,
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionError("Admin access required")


def _create_alert_rule(
    info: Info, workspace_id: str, event_type: str, name: str = ""
) -> AlertRuleType:
    ctx = require_auth(info)
    _require_admin(ctx.user_id, workspace_id)

    try:
        event_choice = AlertRule.EventType(event_type)
    except ValueError:
        raise GraphQLError(
            f"Invalid event_type: {event_type}",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError("Workspace not found")

    rule_name = name or event_type
    rule = AlertRule.objects.create(
        workspace=workspace,
        name=rule_name,
        event_type=event_choice,
    )
    logger.info(
        "alert_rule_created",
        rule_id=str(rule.id),
        workspace_id=workspace_id,
        event_type=event_type,
    )
    return AlertRuleType(
        id=str(rule.id),
        workspace_id=workspace_id,
        name=rule.name,
        event_type=rule.event_type,
        enabled=rule.enabled,
        created_at=rule.created_at.isoformat(),
    )


def _toggle_alert_rule(info: Info, rule_id: str, enabled: bool) -> AlertRuleType:
    ctx = require_auth(info)

    try:
        rule = AlertRule.objects.select_related("workspace").get(id=rule_id)
    except AlertRule.DoesNotExist:
        raise GraphQLError("Alert rule not found")

    _require_admin(ctx.user_id, str(rule.workspace_id))
    rule.enabled = enabled
    rule.save(update_fields=["enabled"])
    return AlertRuleType(
        id=str(rule.id),
        workspace_id=str(rule.workspace_id),
        name=rule.name,
        event_type=rule.event_type,
        enabled=rule.enabled,
        created_at=rule.created_at.isoformat(),
    )


def _connect_channel(
    info: Info, workspace_id: str, channel_type: str, config: str
) -> ChannelPayload:
    """config is a JSON string (e.g. '{"webhook_url":"https://..."}')."""
    import json

    ctx = require_auth(info)
    _require_admin(ctx.user_id, workspace_id)

    try:
        type_choice = NotificationChannel.ChannelType(channel_type)
    except ValueError:
        raise GraphQLError(
            f"Invalid channel type: {channel_type}",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )

    try:
        config_dict = json.loads(config)
    except (json.JSONDecodeError, ValueError):
        raise GraphQLError(
            "config must be valid JSON",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError("Workspace not found")

    channel = NotificationChannel.objects.create(
        workspace=workspace,
        type=type_choice,
        config=config_dict,
    )
    logger.info(
        "channel_connected",
        channel_id=str(channel.id),
        workspace_id=workspace_id,
        type=channel_type,
    )
    return ChannelPayload(
        id=str(channel.id),
        workspace_id=workspace_id,
        type=channel.type,
        enabled=channel.enabled,
        created_at=channel.created_at.isoformat(),
    )


def _disconnect_channel(info: Info, channel_id: str) -> bool:
    ctx = require_auth(info)

    try:
        channel = NotificationChannel.objects.get(id=channel_id)
    except NotificationChannel.DoesNotExist:
        raise GraphQLError("Channel not found")

    _require_admin(ctx.user_id, str(channel.workspace_id))
    channel.delete()
    return True


def _set_quiet_hours(
    info: Info,
    workspace_id: str,
    enabled: bool,
    start_time: str,
    end_time: str,
    timezone: str = "UTC",
    weekdays_only: bool = False,
) -> QuietHoursType:
    ctx = require_auth(info)
    _require_admin(ctx.user_id, workspace_id)

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError("Workspace not found")

    qh, _ = QuietHours.objects.update_or_create(
        workspace=workspace,
        defaults={
            "enabled": enabled,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": timezone,
            "weekdays_only": weekdays_only,
        },
    )
    return QuietHoursType(
        id=str(qh.id),
        workspace_id=workspace_id,
        enabled=qh.enabled,
        start_time=str(qh.start_time),
        end_time=str(qh.end_time),
        timezone=qh.timezone,
        weekdays_only=qh.weekdays_only,
    )


@strawberry.mutation
async def create_alert_rule(
    info: Info, workspace_id: str, event_type: str, name: str = ""
) -> AlertRuleType:
    return await sync_to_async(_create_alert_rule)(info, workspace_id, event_type, name)


@strawberry.mutation
async def toggle_alert_rule(info: Info, rule_id: str, enabled: bool) -> AlertRuleType:
    return await sync_to_async(_toggle_alert_rule)(info, rule_id, enabled)


@strawberry.mutation
async def connect_channel(
    info: Info, workspace_id: str, channel_type: str, config: str
) -> ChannelPayload:
    return await sync_to_async(_connect_channel)(
        info, workspace_id, channel_type, config
    )


@strawberry.mutation
async def disconnect_channel(info: Info, channel_id: str) -> bool:
    return await sync_to_async(_disconnect_channel)(info, channel_id)


@strawberry.mutation
async def set_quiet_hours(
    info: Info,
    workspace_id: str,
    enabled: bool,
    start_time: str,
    end_time: str,
    timezone: str = "UTC",
    weekdays_only: bool = False,
) -> QuietHoursType:
    return await sync_to_async(_set_quiet_hours)(
        info, workspace_id, enabled, start_time, end_time, timezone, weekdays_only
    )
