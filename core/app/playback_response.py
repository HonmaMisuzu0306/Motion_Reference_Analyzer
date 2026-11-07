"""Starlette byte-range handling backed by the already verified open descriptor."""
import os
from contextlib import asynccontextmanager

import anyio
from starlette.responses import FileResponse

from video.playback_file import check_key


class PlaybackResponse(FileResponse):
    def __init__(self, path, file, key):
        self.file = file
        self.key = key
        super().__init__(path, media_type='video/mp4', stat_result=os.fstat(file.fileno()),
                         headers={'Cache-Control': 'private, no-store'})

    async def __call__(self, scope, receive, send):
        # pathsend lets the web server reopen the name after the response exits.
        extensions = {k: v for k, v in scope.get('extensions', {}).items() if k != 'http.response.pathsend'}
        try:
            await super().__call__({**scope, 'extensions': extensions}, receive, send)
        finally:
            self.file.close()

    @asynccontextmanager
    async def _open_file(self):
        yield self

    async def seek(self, offset):
        return await anyio.to_thread.run_sync(self.file.seek, offset)

    async def read(self, size):
        def read_checked():
            data = self.file.read(size)
            # POSIX permits writing through another descriptor. Do not deliver a
            # chunk if that inode changed since verification. Rename alone keeps
            # us on the previously verified descriptor.
            if os.name != 'nt':
                check_key(self.file, self.key)
            return data
        return await anyio.to_thread.run_sync(read_checked)
