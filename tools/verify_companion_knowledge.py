"""Synthetic text with the configured provider; no recording or hardware playback."""
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from reachy_lol.cloud import Cloud
from reachy_lol.long_memory import LongMemory
from reachy_lol.opgg import champion_build


async def main():
    root=Path(__file__).resolve().parents[1]
    load_dotenv(root/'.env')
    cloud=Cloud(lambda _:None)
    memory=LongMemory(root)
    try:
        build=await champion_build('Qiyana')
        item_ids=[id for b in [build,*build['alternatives']] for id in b['data']['core_items']['ids']]
        cases=[('vent','默默，这些队友是死人吗，喊半天都没人跟，气死我了！',[]),
               ('item','金身是什么，有什么效果？',[memory.context('金身')]),
               ('build','奇亚娜中单的攻略呢，先出什么，后面怎么出？',[build,memory.context('',item_ids)])]
        async def check(name,text,knowledge):
            turn=await cloud.owner_turn('aqi',text,None,knowledge,{}, {'name':'默默'})
            return {'case':name,'input':text,'reply':turn.model_dump()}
        rows=await asyncio.gather(*(check(*case) for case in cases))
        result={'kind':'synthetic_text_provider_check','hardware_playback':False,'sample_champion_is_not_user_identity':True,
                'build_reference':build,'results':rows}
        (root/'evidence'/'companion-knowledge-provider.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(rows,ensure_ascii=False,indent=2))
        if not all(row['reply'].get('reply') for row in rows):raise SystemExit(1)
    finally:
        await cloud.client.aclose()


if __name__=='__main__':asyncio.run(main())
