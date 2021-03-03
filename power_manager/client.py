#!/usr/bin/env python3
import json
import logging
import socket
import urllib.parse
import urllib.request
from enum import Enum
from threading import Condition, Lock, Thread

logger = logging.getLogger(__name__)


class TimeoutException(Exception):
    pass


class NonOkException(Exception):
    pass


class State(Enum):
    OFFLINE = 0
    TURNING_ON = 1
    ONLINE = 2


class Client:
    def __init__(self, domain, token_id=None, update_each_sec=60, expire_in_sec=180):
        self._domain = domain
        self._token_id = token_id
        self._update_each_sec = update_each_sec
        self._expire_in_sec = expire_in_sec
        self._lock = Lock()
        self._acquire_cond = Condition(self._lock)
        self._update_cond = Condition(self._lock)
        self._thread = None
        self._state = State.OFFLINE
        self._rc = 0

    def acquire(self):
        with self._lock:
            self._rc += 1
            if self._state == State.OFFLINE:
                self._state = State.TURNING_ON
                self._update_cond.notify()
            while self._state != State.ONLINE:
                self._acquire_cond.wait()

    def release(self):
        with self._lock:
            self._rc -= 1

    def start(self):
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            with self._lock:
                if not self._update_cond.wait(timeout=self._update_each_sec):
                    if self._rc == 0 and self._state == State.ONLINE:
                        self._state = State.OFFLINE
                if self._rc > 0:
                    self._update()
                while self._rc > 0 and self._state != State.ONLINE:
                    if self._is_online():
                        self._state = State.ONLINE
                        self._acquire_cond.notify_all()
                    else:
                        self._update_cond.wait(timeout=20)
                    self._update()

    def _is_online(self):
        try:
            return self._call("/status")['online']
        except TimeoutException:
            logger.warning("Obtained a timeout obtaining the status")
        except NonOkException:
            logger.warning("Obtained a invalid http status")
        return False

    def _update(self):
        try:
            params = {'expire_in_sec': self._expire_in_sec}
            if self._token_id is not None:
                params['id'] = self._token_id
            payload = self._call("/tokens/update", params=params)
            if self._token_id is None:
                self._token_id = payload['id']
        except TimeoutException:
            logger.warning("Obtained a timeout obtaining the status")
        except NonOkException:
            logger.warning("Obtained a invalid http status")

    def _call(self, path, params=None, assert_code=None):
        url = f"{self._domain}{path}"
        if params is not None:
            url_values = urllib.parse.urlencode(params)
            url = f"{url}?{url_values}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if not (200 <= r.status < 300):
                    raise NonOkException
                return json.loads(r.read())
        except socket.timeout:
            raise TimeoutException
