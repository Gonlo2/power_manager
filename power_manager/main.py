#!/usr/bin/env python3
import asyncio
import os
from typing import Optional

import aiosqlite
from fastapi import FastAPI

from .server import Server, setup_db

power_manager = None

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    global power_manager

    db_path = os.environ.get('DB_PATH', 'db.sqlite')
    db = await aiosqlite.connect(db_path)
    await setup_db(db)

    power_manager = Server(
        db,
        os.environ['PM_HOST'],
        os.environ['PM_MAC'],
        int(os.environ.get('PM_EXPIRE_DELAY', 300)),
        int(os.environ.get('PM_GRACEFULL_TIME', 60))
    )
    asyncio.ensure_future(power_manager.loop())

@app.on_event("shutdown")
async def shutdown_event():
    await power_manager.close()

@app.get("/tokens/update")
async def update_token(id: Optional[str] = None, expire_in_sec: Optional[int] = None):
    id = await power_manager.update_token(
        id=id,
        expire_in_sec=expire_in_sec,
    )
    return {'id': id}

@app.get("/tokens/delete/{id}")
async def delete_token(id: str):
    await power_manager.delete_token(id)
    return {}

@app.get('/tokens/list')
async def list_tokens():
    return await power_manager.list_tokens()

@app.get('/status')
async def status():
    return {'online': await power_manager.is_online()}
