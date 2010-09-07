"""
The Client class, used for accessing JSONRPCTCP Server instances. It
shouldn't need to be instantiated directly, instead, use the
connect function:

conn = connect('localhost', 8001)
result = conn.method(param1, param2)
result = conn.tree.method(keyword=arg)
"""

import socket 
import uuid
from jsonrpctcp import config
from jsonrpctcp import history
from jsonrpctcp.logger import logger
from jsonrpctcp.errors import ProtocolError

try:
    import json
except ImportError:
    import simplejson as json

class Client(object):
    """
    This is the JSON RPC client class, which translates attributes into
    function calls and request / response translations, and organizes
    batches, notifications, etc.
    """
    _requests = None
    _request = None
    _response = None

    def __init__(self, addr, batch=False):
        self._addr = addr
        self._requests = []
        self.__batch = batch
        self._responses = None
        
    def __getattr__(self, key):
        if key.startswith('_'):
            raise AttributeError('Methods that start with _ are not allowed.')
        req_id = u'%s' % uuid.uuid4()
        request = ClientRequest(self, namespace=key, req_id=req_id)
        self._requests.append(request)
        return request
        
    @property
    def _notify(self):
        """
        Returns a specialized version of the ClientRequest object,
        which is prepped for notification.
        """
        request = ClientRequest(
            self,
            notify = True,
            req_id = None
        )
        self._requests.append(request)
        return request
        
    def _batch(self):
        """
        Returns a specialized version of the Client class, prepped for
        a series of calls which will only be sent when the Client is
        __call__()ed.
        """
        return Client(self._addr, batch=True)
        
    def _is_batch(self):
        """ Checks whether the batch flag is set. """
        return self.__batch is True
        
    def __call__(self):
        assert len(self._requests) > 0
        requests = []
        for req in self._requests:
            requests.append(req._request())
        if not self._is_batch():
            result = self._call_single(requests[0])
        else:
            result = self._call_batch(requests)
        self._requests = []
        return result
            
    def _call_single(self, request):
        """
        Processes a single request, and returns the response.
        """
        self._request = request
        message = json.dumps(request)
        notify = False
        if not request.has_key('id'):
            notify = True
        response_text = self._send_and_receive(message, notify=notify)
        response = self._parse_response(response_text)
        if not response:
            return response
        self._response = response        
        validate_response(response)
        return response['result']
        
    def _call_batch(self, requests):
        """
        Processes a batch, and returns a generator to iterate over the
        response results.
        """
        ids = []
        for request in requests:
            if request.has_key('id'):
                ids.append(request['id'])
        self._request = requests
        message = json.dumps(requests)
        notify = False
        if len(ids) == 0:
            notify = True
        response_text = self._send_and_receive(
            message, batch=True, notify=notify
        )
        responses = self._parse_response(response_text)
        if not responses:
            raise StopIteration
        self._responses = responses
        assert type(responses) is list
        response_by_id = {}
        for response in responses:
            response_by_id[response.get('id', None)] = response
        for request_id in ids:
            response = response_by_id.get(request_id)
            validate_response(response)
            yield response['result']
    
    def _send_and_receive(self, message, batch=False, notify=False):
        """
        Handles the socket connection, sends the JSON request, and
        (if not a notification) retrieves the response and decodes the
        JSON text.
        """
        # Starting with a clean history
        history.request = message
        logger.debug('CLIENT | REQUEST: %s' % message)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(config.timeout)
        sock.connect(self._addr)
        sock.send(message)
        
        response = ''
        if notify:
            # single notification, we don't need a response.
            sock.close()
        else:
            while True:
                try:
                    data = sock.recv(config.buffer)
                except socket.timeout:
                    break
                if not data: 
                    break
                response += data
                if len(response) < config.buffer:
                    break
            sock.close()
        logger.debug('CLIENT | RESPONSE: %s' % response)
        history.response = response
        return response
        
    def _parse_response(self, response):
        if response == '':
            return None
        try:
            obj = json.loads(response)
        except ValueError:
            raise ProtocolError(-32700)
        if type(obj) is dict and obj.has_key('error'):
            raise ProtocolError(
                obj.get('error').get('code'),
                obj.get('error').get('message'),
                obj.get('error').get('data', None)
            )
        return obj
           
class ClientRequest(object):
    """
    This is the class that holds all of the namespaced methods,
    as well as whether or not it is a notification. When it is
    finally called, it parses the arguments and passes it to
    the parent Client.
    """

    def __init__(self, client, namespace='', notify=False, req_id=None):
        self._client = client
        self._namespace = namespace
        self._notify = notify
        self._req_id = req_id
        self._params = None

    def __getattr__(self, key):
        if key.startswith('_'):
            raise AttributeError
        if self._namespace:
            self._namespace += '.'
        self._namespace += key
        return self
    
    def __call__(self,  *args, **kwargs):
        if not (len(args) == 0 or len(kwargs) == 0):
            raise ValueError(
                "JSON spec allows positional arguments OR " + \
                "keyword arguments, not both."
            )
        params = list(args)
        if len(kwargs) > 0:
            params = kwargs
        return self._call_server(params)
        
    def _call_server(self, params):
        """
        Forms a valid jsonrpc query, and passes it on to the parent
        Client, returning the response.
        """
        self._params = params
        if not self._client._is_batch():
            return self._client()
        # Add batch logic here
        
    def _request(self):
        request = {
            'jsonrpc':'2.0', 
            'method': self._namespace
        }
        if self._params:
            request['params'] = self._params
        if not self._notify:
            request['id'] = self._req_id
        return request
        
def connect(host, port):
    """
    This is a wrapper function for the Client class.
    """
    client = Client((host, port))
    return client
    
def validate_response(response):
    """
    Parses the returned JSON object, verifies that it follows
    the JSON-RPC spec, and checks for errors, raising exceptions
    as necessary.
    """
    jsonrpc = response.has_key('jsonrpc')
    response_id = response.has_key('id')
    result = response.has_key('result')
    error = response.has_key('error')
    if not jsonrpc or not response_id or (not result and not error):
        raise Exception('Server returned invalid response.')
    if error:
        raise ProtocolError(
            response['error']['code'], 
            response['error']['message']
        )
        
def test_client():
    """
    This is the test client to be run against the test_server in
    the server module.
    """
    conn = connect('localhost', 8080)
    value = 'Testing!'
    result = conn.echo(value)
    assert result == value
    print 'Single test completed.'
    
    result = conn._notify.echo(message='No response!')
    assert result == None
    print 'Notify test completed.'
    
    batch = conn._batch()
    batch.tree.echo(message="First!")
    batch._notify.echo("Skip!")
    batch.tree.echo("Last!")
    results = []
    for i in batch():
        results.append(i)
    assert results == ['First!', 'Last!']
    print 'Batch test completed.'
    
    result = conn.echo(message=5)
    assert result == 5
    print 'Post-batch test completed.'
    
    try:
        conn.echo()
    except Exception:
        print 'Bad call had necessary exception.'
    else:
        print 'ERROR: Did not throw exception for bad call.'
    
    print '============================='
    print "Tests completed successfully."
    
if __name__ == "__main__":
    import sys    
    import logging
    if '-v' in sys.argv:
        config.verbose = True
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler())
    test_client()
