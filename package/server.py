import grpc
import random
from concurrent import futures
import time

import server_services_pb2_grpc
import server_services_pb2

import client_services_pb2
import client_services_pb2_grpc

class FileServicesImplementation(server_services_pb2_grpc.FileServicesServicer):
  def __init__(self) -> None:
    super().__init__()
    # self.metadata = {}
    self.files = {}
    self.hosts = {}

  def Initialize(self, request, context):
    '''
    Will be called for the first time only
    '''
    name = str(request.name)
    files = list(request.files)
    hostname = request.connection_string
    # self.metadata[name] = {
    #   files: files
    # }
    for file in files:
      self.files[file] = [name] # This will hold all the clients that can serve the file, first holds the master copy
    self.hosts[name] = {
      "last_message": time.time(),
      "hostname": hostname
    }

    print(f'Host {name} has been successfully registered on {self.hosts[name]["last_message"]}')

    response = server_services_pb2.InitializeResponse()
    response.status = True
    return response

  def KeepAlive(self, request, context):
    response = server_services_pb2.KeepAliveResponse()
    name = request.name
    if name not in self.hosts:
      print(f'Error: No such client as {name} has connected before.')
      response.status = False
      return response
    
    new_files = request.new_files
    deleted_files = request.deleted_files
    changed_files = request.changed_files

    # self.metadata[name].files.extend(new_files)
    for file in new_files:
      self.files[file] = [name]

    # self.metadata[name].files = list(filter(lambda x: x not in deleted_files, self.metadata[name].files))
    for file in deleted_files:
      del self.files[file]

    for file in changed_files:
      # self.files[file] = [name] # Reset and remove all other clients for these files
      for host in self.files[file][1:]:
        # Make request to each host and let them know the file is stale
        channel = grpc.insecure_channel(self.hosts[host]['hostname'])
        stub = client_services_pb2_grpc.P2PFileServicesStub(channel)
        mark_stale_request = client_services_pb2.MarkStaleRequest(file=file)
        stub.MarkStale(mark_stale_request)

    self.hosts[name]["last_message"] = time.time()

    print(f'Host {name} has sent an update message on {self.hosts[name]["last_message"]}')

    response.status = True
    return response

  def GetFiles(self, request, context):
    response = server_services_pb2.GetFilesResponse()
    response.files.extend(self.files.keys())
    return response

  def GetFileNode(self, request, context):
    response = server_services_pb2.GetFileNodeResponse()
    file = request.file
    if file not in self.files:
      response.status = False
      response.hostname = ''
      return response

    name = random.choice(self.files[file])
    response.hostname = self.hosts[name]['hostname']
    response.status = True
    print(f'Host has requested to download file {file} from {name}')
    return response

  def AddFileNode(self, request, context):
    response = server_services_pb2.FileNodeResponse()
    name = request.name
    file = request.file

    if file not in self.files:
      print(f'No such file {file}')
      response.status = False
      return response

    self.files[file].append(name)
    response.status = True
    print(f'Host {name} has requested to register itself for file {file}')
    return response

  def RemoveFileNode(self, request, context):
    response = server_services_pb2.FileNodeResponse
    name = request.name
    file = request.file

    if file not in self.files:
      print(f'No such file {file}')
      response.status = False
      return response

    self.files[file] = list(filter(lambda x: x != name, self.files[file]))
    response.status = True
    print(f'Host {name} has requested to remove itself for file {file}')
    return response

server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
server_services_pb2_grpc.add_FileServicesServicer_to_server(FileServicesImplementation(), server)

port = 8000

print(f'DFS Server has started on localhost:{port}')
server.add_insecure_port(f'[::]:{port}')
server.start()

try:
  while True:
    time.sleep(8400)
except KeyboardInterrupt:
  print("Exiting server")
  server.stop(0)