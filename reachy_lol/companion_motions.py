"""Shared model whitelist and one event-loop controller for HF expressions."""
import asyncio
import concurrent.futures
import time
from reachy_skills import COMMUNITY_MOVES, CombinedLibrary, ExpressionTools, load_community_library

MOTIONS = ('nod','tilt','neutral', *COMMUNITY_MOVES)
MOTION_STYLE = (
    'motion可选nod/tilt/neutral或HF预设ID。按情绪优先选HF：'
    '认真倾听stella.slow_nod、认可stella.double_nod、安抚anne.chill、'
    '同仇敌忾接吐槽anne.no_way、俏皮接梗generated.sassy、开心generated.joy、'
    '庆祝generated.shy_celebrate、思考stella.think；不必句句动，普通回答neutral。'
    '动作无音效，不在text念动作名。'
)


class CompanionMotions:
    def __init__(self):
        self.loop=None
        self.library=None
        self.controller=None
        self.errors=[]

    async def preload(self):
        self.loop=asyncio.get_running_loop()
        semaphore=asyncio.Semaphore(4)
        async def load(id):
            async with semaphore:
                try:
                    return await asyncio.to_thread(load_community_library,[id],with_audio=False)
                except Exception as exc:
                    self.errors.append({'skill_id':id,'error':type(exc).__name__})
        libraries=await asyncio.gather(*(load(id) for id in COMMUNITY_MOVES))
        self.library=CombinedLibrary(*(library for library in libraries if library is not None))

    def summary(self):
        return {'loaded':list(self.library.list_moves()) if self.library else [],
                'total':len(COMMUNITY_MOVES),'errors':self.errors,'sound':False}

    def stop(self):
        if self.controller and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.controller.stop_expression)

    async def play(self,robot,skill_id,valid):
        if not valid():return {'status':'stopped'}
        if self.controller is None or self.controller.robot is not robot:
            self.controller=ExpressionTools(robot,self.library,dry_run=False)
        return await self.controller.play_expression_skill(skill_id,sound=False)

    def play_from_worker(self,robot,skill_id,valid):
        # Called under Robot.lock, never blocks the application's event loop.
        if not self.loop or not self.loop.is_running() or not self.library or skill_id not in self.library.list_moves():
            return {'status':'unavailable','skill_id':skill_id,'command_sent':False}
        future=asyncio.run_coroutine_threadsafe(self.play(robot,skill_id,valid),self.loop)
        deadline=time.monotonic()+45
        try:
            while True:
                if not valid() or time.monotonic()>deadline:
                    self.stop()
                    future.cancel()
                    return {'status':'stopped','skill_id':skill_id}
                try:
                    return future.result(timeout=.05)
                except concurrent.futures.TimeoutError:
                    continue
        except BaseException:
            future.cancel()
            raise
