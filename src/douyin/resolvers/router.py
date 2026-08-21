from douyin.models import VideoInfo
from douyin.resolvers.base import Resolver, ResolverError


class ResolverRouter:
    def __init__(self, resolvers: list[Resolver]):
        self.resolvers = resolvers

    async def resolve(self, input_text: str) -> VideoInfo:
        errors: list[str] = []
        for resolver in self.resolvers:
            try:
                if await resolver.probe():
                    return await resolver.resolve(input_text)
            except Exception as exc:
                errors.append(f"{resolver.name}: {exc}")
        raise ResolverError("All resolvers failed: " + "; ".join(errors))
