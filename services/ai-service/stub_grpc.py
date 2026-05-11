"""Serveur gRPC vide — intégration Ollama + protos à l’étape AI Service."""

from __future__ import annotations

import os
from concurrent import futures

import grpc


def serve() -> None:
    port = os.environ["GRPC_PORT"]
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    host = os.environ.get("OLLAMA_HOST", "")
    print(f"[ai-service] stub gRPC on :{port} (OLLAMA_HOST={host})", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
