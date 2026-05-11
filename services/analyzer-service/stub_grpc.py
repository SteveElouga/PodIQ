"""Serveur gRPC vide jusqu’à codegen analyzer."""

from __future__ import annotations

import os
from concurrent import futures

import grpc


def serve() -> None:
    port = os.environ["GRPC_PORT"]
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    print(f"[analyzer-service] stub gRPC listening on :{port}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
