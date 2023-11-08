import grpc

# import the generated classes
import server_services_pb2
import server_services_pb2_grpc

# open a gRPC channel
channel = grpc.insecure_channel('localhost:8000')

# create a stub (client)
stub = server_services_pb2_grpc.GreetingStub(channel)

# create a valid request message
name = 'your_name'
request = server_services_pb2.GreetingRequest(name=name)

# make the call
response = stub.Hello(request)

print(response.response)
