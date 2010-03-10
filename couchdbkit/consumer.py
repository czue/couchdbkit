# -*- coding: utf-8 -
#
# This file is part of couchdbkit released under the MIT license. 
# See the NOTICE for more information.

import asyncore
import asynchat
import socket
import sys
try:
    import simplejson as json
except ImportError:
    import json
    
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
    
from couchdbkit.resource import encode_params
class Consumer(object):
    """ Database change consumer
    
    Example Usage:
    
        >>> from couchdbkit import Server, Consumer
        >>> s = Server()
        >>> db = s['testdb']
        >>> c = Consumer(db)
        >>> def print_line(line):
        ...     print "got %s" % line
        ... 
        >>> c.register_callback(print_line)
        >>> c.wait() # Go into receive loop
         
    """
    
    def __init__(self, db):
        self.db = db
        self.callbacks = []
        self._resp = None

    def register_callback(self, callback):
        """ Register a callback on which changes will
        be sent with `wait_once` and `wait`methods. 
        """
        
        if not callable(callback):
            raise TypeError("callback isn't a callable")
        self.callbacks.append(callback)

    def _make_params(self, feed, since, heartbeat, timeout, filter):
        params = {"feed": feed}
        if since: params["since"] = since
        if heartbeat:
            params["heartbeat"] = heartbeat
        elif timeout:
            params["timeout"] = timeout
        if filter: params["filter"] = filter_name
        return encode_params(params)
        
    def fetch(self, since=None, filter_name=None):
        """ Fetch all changes and return. If since is specified, fetch all changes
        since this doc sequence
        
        Args:
        @param since: str or int, sequence from which you want to get changes
        @param filter_name: filter_name to use
        
        @return: dict, change result
        
        """
        params = {}
        if since: params['since'] = since
        if filter_name: params["filter"] = filter_name
        resp = self.db.get("_changes", **params)
        return resp.json_body
        
    def wait_once(self, since=None, heartbeat=False, timeout=60000, 
            filter_name=None):
        """Wait for one change and return (longpoll feed) 
        
        Args:
        @param since: str or int, sequence from which you want to get changes
        @param heartbeat: boolean, try to maintain connection by sending '\n'
        @param timeout: int, timeout in ms
        @param filter_name: filter_name to use
        
        @return: dict, change result
        """
        params = self._make_params("longpoll", since, heartbeat, 
                            timeout, filter_name)
        resp = self.db.get("_changes", **params)
        buf = StringIO()
        while True:
            data = resp.body_file.read()
            if not data: break
            buf.write(data)
            
        ret = json.loads(buf.getvalue())
        for callback in self.callbacks:
            callback(ret)
        return ret
        
    def wait(self, since=None, heartbeat=True, timeout=None, filter_name=None):
        """ Wait for changes until the connection close (continuous feed)
        
        Args:
        @param since: str or int, sequence from which you want to get changes
        @param heartbeat: boolean, try to maintain connection by sending '\n'
        @param timeout: int, timeout in ms
        @param filter_name: str, filter_name to use
        
        @return: dict, line of change
        """
        params = self._make_params("continuous", since, heartbeat, 
                            timeout, filter_name)
        self._resp = resp = self.db.get("_changes", **params)
        
        if resp.headers.get('transfer-encoding') == "chunked":
            chunked = True
        else:
            chunked = False
        
        try:
            change_handler = continuous_changes_handler(resp, 
                                            self.callbacks, chunked)
            asyncore.loop()
        except:
            self.close()
            raise
            
    def close(self):
        if self._resp is None:
            return
        #self._resp.http_client.maybe_close()
        self._resp = None
        
        
class continuous_changes_handler(asynchat.async_chat):
    
    def __init__(self, resp, callbacks, chunked):
        self.resp = resp
        self.callbacks = callbacks
        self.chunked = chunked
        self.buf = [resp._body.tmp.read()]
        self._sock = sock = resp.http_client._sock
        asynchat.async_chat.__init__(self, sock=sock)
        if self.chunked:
            self.set_terminator("\r\n")
        else:
            self.set_terminator("\n")
        self.chunk_left = False
        
    def handle_close(self):
        try:
            self._sock.close()
        except:
            pass
        
    def collect_incoming_data(self, data):
        if self.chunked:
            if not self.chunk_left:
                return
                
            self.buf.append(data)
        else:
            self.buf.append(data)
            
    def found_terminator(self):
        if self.chunked and not self.chunk_left:
            # we got the length
            self.chunk_left = True
            self.buf = []
            return
            
        line = "".join(self.buf)
        self.buf = []
        if self.chunked: 
            self.chunk_left = False
            line = line.strip()

        if line:
            line = json.loads(line)
            for callback in self.callbacks:
                callback(line)