import grpc
from concurrent import futures
import time

import server_services_pb2_grpc
import server_services_pb2

class GreetingImplementation(server_services_pb2_grpc.GreetingServicer):
  def Hello(self, request, context):
    response = server_services_pb2.GreetingResponse()
    response.response = f"Hello {request.name}"
    return response
  
server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

server_services_pb2_grpc.add_GreetingServicer_to_server(GreetingImplementation(), server)

print("Starting server on port 8000...")
server.add_insecure_port('[::]:8000')
server.start()

try:
  while True:
    time.sleep(5000)
except KeyboardInterrupt:
  server.stop(0)
