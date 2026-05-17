from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import GraphQLView

from app.api.cicd import scan
from app.graphql.schema import schema


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path("graphql", csrf_exempt(GraphQLView.as_view(schema=schema))),
    path("api/v1/cicd/scan", scan),
]
