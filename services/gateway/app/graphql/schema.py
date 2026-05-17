import strawberry

from app.graphql.mutations.analyze import analyze_incident
from app.graphql.mutations.auth import create_api_key, login, register, revoke_api_key
from app.graphql.mutations.scan_manifest import scan_manifest
from app.graphql.queries.history import analysis_history
from app.graphql.queries.job import analysis_job


@strawberry.type
class Query:
    analysis_history = analysis_history
    analysis_job = analysis_job


@strawberry.type
class Mutation:
    analyze_incident = analyze_incident
    scan_manifest = scan_manifest
    register = register
    login = login
    create_api_key = create_api_key
    revoke_api_key = revoke_api_key


schema = strawberry.Schema(query=Query, mutation=Mutation)
