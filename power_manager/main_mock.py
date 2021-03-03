#!/usr/bin/env python3
from typing import Optional

from fastapi import FastAPI

from .server import generate_tmp_id

app = FastAPI()

@app.get("/tokens/update")
async def update_token(id: Optional[str] = None, expire_in_sec: Optional[int] = None):
    if id is None:
        id = generate_tmp_id()
    return {'id': id}

@app.get("/tokens/delete/{id}")
async def delete_token(id: str):
    return {}

@app.get('/tokens/list')
async def list_tokens():
    raise NotImplementedError

@app.get('/status')
async def status():
    return {'online': True}
