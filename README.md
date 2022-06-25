# introduce

this project is `https://github.com/joshmarshall/jsonrpctcp`improvement and support python3+
implementation tcp jsonrpc protocol

## useage

1. define service
```python
import logging

from jsonrpctcp.handler import Handler

class HelloService(Handler):

    def getName(self, args: str):
        logging.info("this is getName")
        return f"hello {args}"

```

2. server example

```python
from typing import List

from jsonrpctcp.server import Server
from jsonrpctcp import config
from jsonrpctcp.handler import Handler

from hello_service import HelloService


class RpcTcpServer:
    port: int

    def __init__(self, port: int = 3545):
        self.port = port
        config.buffer = 4096
        config.verbose = True
        config.timeout = 3

    def register_service(self) -> List[Handler]:
        handlers: List[(str, Handler)] = [
            ("HelloService", HelloService())
        ]
        return handlers

    def listen_and_accept(self):
        socket_server = Server(addr=("", self.port))
        # register service
        handlers = self.register_service()
        for name, handler in handlers:
            socket_server.add_handler(handler, name)

        # listen
        socket_server.serve()


server = RpcTcpServer()
server.listen_and_accept()

```

3. cilent example
```python
import json
import logging
import socket
from typing import Union
import itertools
import json


class RPCTcpClient:

    def __init__(self, codec=json):
        timeout = 3
        host = "localhost"
        port = 3545
        self.buffer_size = 4096
        self._id_iter = itertools.count()
        self._socket = socket.create_connection((host, port))
        self._socket.settimeout(timeout)
        self._codec = codec

    def _message(self, name, *params) -> dict:
        return dict(id=next(self._id_iter), params=list(params), method=name)

    def call(self, name, *params) -> Union[dict, str]:
        payload = self._message(name, *params)
        msg = self._codec.dumps(payload)
        self._socket.sendall(msg.encode())

        rsp = ""
        while True:
            rsp_segment_bytes = self._socket.recv(self.buffer_size)
            rsp += rsp_segment_bytes.decode()
            print(rsp)
            if len(rsp_segment_bytes) < self.buffer_size:
                break
        # output: {"id":0,"result":"args: python, my is HelloService","error":null}
        result = {}
        rsp_dict = self._codec.loads(rsp)
        # print(rsp_dict)
        if rsp_dict.get("id") != payload.get("id"):
            logging.error("except id: %s, received id: %s: %s", payload.get("id"), rsp_dict.get("id"),
                          rsp_dict.get("error"))
        elif rsp_dict.get("error"):
            logging.error("rpc error: req_id: %d, error: %s", payload.get("id"), rsp_dict["error"])
        else:
            result = rsp_dict.get("result")
        return result

    def close(self):
        self._socket.close()

rpc_client = RPCTcpClient()
res = rpc_client.call("HelloService.getName", "python")
print(res)

```
