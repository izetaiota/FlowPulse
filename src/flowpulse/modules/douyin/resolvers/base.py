from typing import Protocol

from flowpulse.modules.douyin.models import VideoInfo


class ResolverError(RuntimeError):
    pass


class Resolver(Protocol):
    name: str

    async def probe(self) -> bool: ...

    async def resolve(self, input_text: str) -> VideoInfo: ...
