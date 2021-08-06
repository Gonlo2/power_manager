#!/usr/bin/env python3
import asyncio
import random
import socket
import string
import time


def generate_tmp_id(size=8):
    letters = string.ascii_letters + string.digits
    id = ''.join(random.choice(letters) for _ in range(size))
    return f"tmp:{id}"

async def run(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait()

async def setup_db(db):
    c = await db.cursor()
    await c.execute(
        '''
        CREATE TABLE IF NOT EXISTS tokens (
            id TEXT NOT NULL,
            expire_time INTEGER NULL,
            PRIMARY KEY (id)
        )

        '''
    )
    await c.execute('CREATE INDEX IF NOT EXISTS expire_time ON tokens (expire_time)')
    await db.commit()

class Server:
    def __init__(self, db, host, mac, expire_delay_sec, shutdown_after_sec):
        self._db = db
        self._host = host
        self._mac = mac
        self._expire_delay_sec = expire_delay_sec
        self._shutdown_after_sec = shutdown_after_sec

        self._shutdown_at_sec = 0
        self._check_status = asyncio.Condition()
        self._running = True
        self._loop_lock = asyncio.Lock()

    async def update_token(self, id=None, expire_in_sec=None):
        if id is None:
            id = generate_tmp_id()
            if expire_in_sec is None:
                expire_in_sec = self._expire_delay_sec

        expire_time = None if expire_in_sec is None else \
            int(time.time()) + expire_in_sec

        query = 'SELECT id FROM tokens WHERE id = ? LIMIT 1'
        c = await self._db.execute(query, (id,))
        result = await c.fetchone()
        if result is None or len(result) == 0:
            query = 'INSERT INTO tokens(id, expire_time) VALUES(?, ?) ON CONFLICT(id) DO NOTHING'
            await c.execute(query, (id, expire_time,))
            async with self._check_status:
                self._check_status.notify_all()
        else:
            query = 'UPDATE tokens SET expire_time = ? WHERE id = ?'
            await c.execute(query, (expire_time, id,))
        await self._db.commit()

        return id

    async def delete_token(self, id):
        query = 'DELETE FROM tokens WHERE id = ?'
        await self._db.execute(query, (id,))
        await self._db.commit()

    async def list_tokens(self):
        tokens = []
        query = 'SELECT id, expire_time FROM tokens'
        c = await self._db.execute(query)
        for id, expire_time in await c.fetchall():
            token = {'id': id, 'expire_time': expire_time}
            tokens.append(token)
        return tokens

    async def loop(self):
        async with self._loop_lock:
            await self._loop()

    async def _loop(self):
        while self._running:
            now_sec = int(time.time())

            if not await self._with_tokens():
                if self._shutdown_at_sec < now_sec:
                    if await self.is_online():
                        await self._shutdown()
            elif not await self.is_online():
                self._wake()
                self._shutdown_at_sec = 0

            query = 'DELETE FROM tokens WHERE expire_time <= ?'
            await self._db.execute(query, (now_sec,))
            await self._db.commit()

            async with self._check_status:
                await self._wait_next_check(now_sec)

        if await self.is_online():
            await self._shutdown()

        await self._db.close()

    async def _with_tokens(self):
        query = 'SELECT id FROM tokens LIMIT 1'
        c = await self._db.execute(query)
        return await c.fetchone() is not None

    def _wake(self):
        mac_as_bytes = bytes([int(x, 16) for x in self._mac.split(':')])
        msg = b'\xff' * 6 + mac_as_bytes * 16

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.connect(('255.255.255.255', 9))
            s.send(msg)
        finally:
            s.close()

    async def is_online(self, timeout=0.1):
        fut = asyncio.open_connection(self._host, 22)
        try:
            _, writer = await asyncio.wait_for(fut, timeout=timeout)
            writer.close()
            return True
        except (OSError, asyncio.TimeoutError):
            pass
        return False

    async def _shutdown(self):
        self._online = await run(f'ssh shutdown-me@{self._host}') != 0

    async def _wait_next_check(self, now_sec):
        timeout = 20
        if not await self._with_tokens():
            if await self.is_online():
                if self._shutdown_at_sec == 0:
                    self._shutdown_at_sec = now_sec + self._shutdown_after_sec
            else:
                timeout = 600

        try:
            await asyncio.wait_for(self._check_status.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def close(self):
        async with self._check_status:
            self._running = False
            self._check_status.notify_all()
        await self._loop_lock.acquire()
