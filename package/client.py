from typing import List, Dict
import threading
import hashlib
import os
import grpc
import argparse
import glob
from collections import defaultdict
from concurrent import futures

# import the generated classes
import server_services_pb2
import server_services_pb2_grpc

import client_services_pb2
import client_services_pb2_grpc

SERVER_PORT = 8000

def read_file(path: str) -> str:
  with open(path, 'r') as f:
    return f.read()

def write_file(path: str, content: str) -> None:
  with open(path, 'w') as f:
    f.write(content)

def list_files(path: str) -> List[str]:
  path = os.path.abspath(path)
  return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)) and not f.startswith('dfs_')] # dfs_ will be local copies

def list_files_dfs(path: str) -> List[str]:
  path = os.path.abspath(path)
  return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

def generate_file_hash(file: str, directory: str) -> str:
  with open(f'{directory}/{file}', 'rb') as f:
    bytes_ = f.read()
    hash_ = hashlib.sha256(bytes_).hexdigest()
    return hash_

def generate_file_hashes(files: List[str], directory: str) -> Dict[str, str]:
  file_hashes = defaultdict()

  for file in files:
    file_hashes[file] = generate_file_hash(file, directory)

  return file_hashes

class Client(client_services_pb2_grpc.P2PFileServicesServicer):
  def __init__(self, **kwargs) -> None:
    self.channel = grpc.insecure_channel(f'localhost:{SERVER_PORT}')
    self.stub = server_services_pb2_grpc.FileServicesStub(self.channel)
    self.name = kwargs['name']
    self.port = kwargs['port']
    self.directory = kwargs['directory']
    self.hostname = f'localhost:{self.port}'
    files = list_files(self.directory)
    self.hashes = generate_file_hashes(files, self.directory)
    self.thread = threading.Thread(target=self._update)
    self.cache = {} # file -> hostname

    # Remove all files with dfs_
    files = glob.glob(f'{self.directory}/dfs_*')
    for file in files:
      if os.path.isfile(file):
        os.remove(file)

  def DownloadFile(self, request, context):
    file = request.file
    response = client_services_pb2.DownloadFileResponse()
    if file not in self.hashes.keys() and file not in self.cache.keys():
      response.content = ''
      response.status = False
      return response

    path = f'{self.directory}/{file}' if file in self.hashes.keys() else f'{self.directory}/dfs_{file}'
    content = read_file(path)
    response.content = content
    response.status = True
    return response

  def MarkStale(self, request, context):
    response = client_services_pb2.MarkStaleResponse()
    file = request.file
    channel = grpc.insecure_channel(self.cache[file])
    stub = client_services_pb2_grpc.P2PFileServicesStub(channel)
    download_file_request = client_services_pb2.DownloadFileRequest(file=file)
    download_file_response = stub.DownloadFile(download_file_request)
    if not download_file_response.status:
      print('Could not download file')
      return response
    write_file(f'{self.directory}/dfs_{file}', download_file_response.content)
    return response

  def Initialize(self) -> None:
    files = list_files(self.directory)
    request = server_services_pb2.InitializeRequest(name=self.name, connection_string=self.hostname, files=files)
    response = self.stub.Initialize(request)
    print(f'Initialized with response {response.status}')
  
  def GetFiles(self) -> List[str]:
    request = server_services_pb2.GetFilesRequest()
    response = self.stub.GetFiles(request)
    return response.files

  def GetFile(self, file: str) -> str:
    # Check local fs, if present just return
    # Make call to server to get node that has the file
    # Make call to node to get the file
    # Update local data structures to mark a new file
    # Return content
    files = list_files(self.directory)
    if file in files:
      # Found in local dir, just return here
      return read_file(f'{self.directory}/{file}')

    # Check cache
    files_dfs = list_files_dfs(self.directory)
    if f'dfs_{file}' in files_dfs:
      return read_file(f'{self.directory}/dfs_{file}')

    get_file_node_request = server_services_pb2.GetFileNodeRequest(file=file)
    get_file_node_response = self.stub.GetFileNode(get_file_node_request)
    if not get_file_node_response.status:
      print('Something went wrong')
      return ''
    
    hostname = get_file_node_response.hostname
    # Make call to the host and get the file
    # Write it in local fs
    # Add the file to node
    channel = grpc.insecure_channel(hostname)
    stub = client_services_pb2_grpc.P2PFileServicesStub(channel)
    download_file_request = client_services_pb2.DownloadFileRequest(file=file)
    download_file_response = stub.DownloadFile(download_file_request)
    if not download_file_response.status:
      print('Could not download file')
      return ''
    write_file(f'{self.directory}/dfs_{file}', download_file_response.content)
    self.cache[file] = hostname

    add_file_node_request = server_services_pb2.FileNodeRequest(name=self.name, file=file)
    self.stub.AddFileNode(add_file_node_request)

    return download_file_response.content

  def start_timer(self) -> None:
    self.thread.start()
    
  def _update(self) -> None:
    while True:
      known_files = self.hashes.keys()
      unknown_files = list_files(self.directory)
      new_files = list(set(unknown_files) - set(known_files))
      deleted_files = list(set(known_files) - set(unknown_files))

      # Remove the hashes of deleted_files
      for file in deleted_files:
        del self.hashes[file]

      changed_files = []
      for file in known_files:
        old_hash = self.hashes[file]
        new_hash = generate_file_hash(file, self.directory)
        if old_hash != '' and old_hash != new_hash:
          changed_files.append(file)
        self.hashes[file] = new_hash

      request = server_services_pb2.KeepAliveRequest(name=self.name, new_files=new_files, deleted_files=deleted_files, changed_files=changed_files)
      self.stub.KeepAlive(request)
      threading.Event().wait(timeout=10.0)

def main():
  parser = argparse.ArgumentParser("client")
  parser.add_argument("name", help="This is a unique name to be identified with", type=str)
  parser.add_argument("directory", help="This is the path to the directory to be mounted", type=str)
  parser.add_argument("port", help="This is the port number on which the client services will run", type=int)

  args = parser.parse_args()
  client = Client(**args.__dict__)
  client.Initialize()
  client.start_timer()

  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  client_services_pb2_grpc.add_P2PFileServicesServicer_to_server(client, server)
  server.add_insecure_port(f'[::]:{args.__dict__["port"]}')
  server.start()

  # CLI Like interface
  while True:
    command = input(f'{client.name} on {client.directory}> ')

    if command == 'get_files':
      files = client.GetFiles()
      print('Files available to browse are: ')
      print('\n'.join(files))
    elif command.startswith('get '):
      content = client.GetFile(command.split('get ')[1])
      print(content)

if __name__ == '__main__':
  main()