import strawberry

from app.graphql.mutations.agent import agent_heartbeat, agent_report_incident
from app.graphql.mutations.analyze import analyze_incident
from app.graphql.mutations.auth import create_api_key, login, register, revoke_api_key
from app.graphql.mutations.install_token import generate_install_token
from app.graphql.mutations.invitation import (
    accept_invitation,
    generate_invite_link,
    invite_member,
    revoke_invitation,
)
from app.graphql.mutations.notifications import (
    connect_channel,
    create_alert_rule,
    disconnect_channel,
    set_quiet_hours,
    toggle_alert_rule,
)
from app.graphql.mutations.scan_manifest import scan_manifest
from app.graphql.mutations.workspace import (
    create_workspace,
    refresh_token,
    select_workspace,
    update_workspace,
)
from app.graphql.queries.cluster import cluster_status
from app.graphql.queries.history import analysis_history
from app.graphql.queries.invitations import list_invitations
from app.graphql.queries.job import analysis_job
from app.graphql.queries.workspace import current_workspace, list_workspaces
from app.graphql.subscriptions.cluster import cluster_connected
from app.graphql.subscriptions.job import job_status


@strawberry.type
class Query:
    analysis_history = analysis_history
    analysis_job = analysis_job
    list_workspaces = list_workspaces
    current_workspace = current_workspace
    cluster_status = cluster_status
    list_invitations = list_invitations


@strawberry.type
class Mutation:
    # Auth
    register = register
    login = login
    create_api_key = create_api_key
    revoke_api_key = revoke_api_key
    # Workspace
    create_workspace = create_workspace
    select_workspace = select_workspace
    refresh_token = refresh_token
    update_workspace = update_workspace
    # Analysis
    analyze_incident = analyze_incident
    scan_manifest = scan_manifest
    # Agent
    generate_install_token = generate_install_token
    agent_heartbeat = agent_heartbeat
    agent_report_incident = agent_report_incident
    # Invitations
    invite_member = invite_member
    revoke_invitation = revoke_invitation
    accept_invitation = accept_invitation
    generate_invite_link = generate_invite_link
    # Notifications
    create_alert_rule = create_alert_rule
    toggle_alert_rule = toggle_alert_rule
    connect_channel = connect_channel
    disconnect_channel = disconnect_channel
    set_quiet_hours = set_quiet_hours


@strawberry.type
class Subscription:
    cluster_connected = cluster_connected
    job_status = job_status


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
