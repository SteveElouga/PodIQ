from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import GraphQLView

from app.graphql.schema import schema


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path("graphql", csrf_exempt(GraphQLView.as_view(schema=schema))),
]
