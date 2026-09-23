"""Read-only official OP.GG MCP; only public champion names leave the machine."""
import ast
import json
import re
from datetime import datetime, timezone
import httpx

ENDPOINT = 'https://mcp-api.op.gg/mcp'
FIELDS = ['champion', 'position', 'data.summary.positions[].name','data.summary.positions[].stats.play',
          'data.core_items.{ids[],ids_names[],pick_rate,play,win}',
          'data.starter_items.{ids[],ids_names[]}', 'data.boots.{ids[],ids_names[]}',
          'data.fourth_items[].{ids[],ids_names[],pick_rate,play,win}',
          'data.skills.order[]', 'data.skill_masteries.ids[]', 'data.trends.win.version']


def decode_data(text):
    """Decode JSON or OP.GG's compact class notation, never execute page code."""
    if len(text) > 100000:
        raise ValueError('OP.GG data too large')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    definitions = {}
    body = []
    for line in text.splitlines():
        match = re.fullmatch(r'class (\w+): ([\w,]+)', line.strip())
        if match:
            definitions[match[1]] = match[2].split(',')
        elif line.strip():
            body.append(line)
    tree = ast.parse('\n'.join(body), mode='eval')
    def walk(node, depth=0):
        if depth > 25:
            raise ValueError('OP.GG nesting too deep')
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
            return node.value
        if isinstance(node, ast.List):
            return [walk(x, depth+1) for x in node.elts]
        if isinstance(node, ast.Name) and node.id in ('null','true','false'):
            return {'null':None,'true':True,'false':False}[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            fields = definitions.get(node.func.id)
            if fields is not None and len(fields) == len(node.args):
                return dict(zip(fields, [walk(x, depth+1) for x in node.args]))
        raise ValueError('Unsupported OP.GG data notation')
    return walk(tree.body)


async def rpc(client, method, params, ident, headers):
    async with client.stream('POST', ENDPOINT, headers=headers,
                             json={'jsonrpc':'2.0', 'id':ident, 'method':method, 'params':params}) as response:
        response.raise_for_status()
        if response.headers.get('mcp-session-id'):
            headers['mcp-session-id'] = response.headers['mcp-session-id']
        parts=[]; size=0
        async for part in response.aiter_bytes():
            size += len(part)
            if size > 1024*1024:
                raise ValueError('OP.GG response too large')
            parts.append(part)
        raw=b''.join(parts).decode('utf8')
        if 'text/event-stream' in response.headers.get('content-type',''):
            messages=[json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith('data:')]
            packet=next((m for m in messages if m.get('id')==ident), {})
        else:
            packet=json.loads(raw)
        if packet.get('error') or 'result' not in packet:
            raise ValueError('OP.GG protocol error')
        return packet['result']


async def champion_build(champion, position='all', client=None):
    # Use Riot's English alias, not nicknames or any account information.
    if not re.fullmatch(r'[A-Za-z_ ]{2,40}', champion):
        raise ValueError('Invalid champion alias')
    if position not in ('all','top','mid','jungle','adc','support'):
        position='all'
    own=client is None
    if own:
        client=httpx.AsyncClient(timeout=12, follow_redirects=False)
    headers={'Accept':'application/json, text/event-stream'}
    try:
        init=await rpc(client,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},
                       'clientInfo':{'name':'reachy-lol','version':'1.0'}},1,headers)
        headers['MCP-Protocol-Version']=init.get('protocolVersion','2025-06-18')
        await client.post(ENDPOINT,headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'})
        async def fetch(lane, ident):
            result=await rpc(client,'tools/call',{'name':'lol_get_champion_analysis','arguments':{
                'champion':champion.upper().replace(' ','_'),'position':lane,'game_mode':'ranked',
                'lang':'zh_CN','desired_output_fields':FIELDS}},ident,headers)
            if result.get('isError'):
                raise ValueError('OP.GG tool unavailable')
            return result.get('structuredContent') or decode_data('\n'.join(
                c['text'] for c in result.get('content',[]) if c.get('type')=='text'))
        # The advertised "all" enum is rejected by the current upstream API.
        # Discover the most-sampled lane from summary, then fetch that lane.
        data=await fetch('mid' if position=='all' else position,2)
        alternative_data=[]
        if position=='all' and isinstance(data,dict):
            lanes=((data.get('data') or {}).get('summary') or {}).get('positions') or []
            if lanes:
                packets=[]
                for index,row in enumerate(sorted(lanes,key=lambda row:(row.get('stats') or {}).get('play',0),reverse=True)[:2]):
                    lane={'MIDDLE':'mid','BOTTOM':'adc','UTILITY':'support'}.get(row['name'],row['name'].lower())
                    if lane in ('top','mid','jungle','adc','support'):
                        packets.append(data if lane=='mid' else await fetch(lane,3+index))
                if packets:
                    data=packets[0];alternative_data=packets[1:]
        if not isinstance(data,dict) or not isinstance(data.get('data'),dict):
            raise ValueError('Invalid OP.GG build')
        details=data['data']
        core=details.get('core_items')
        if not isinstance(core,dict) or not core.get('ids'):
            raise ValueError('OP.GG has no item sample')
        return {'kind':'champion_build', 'champion_key':champion, 'champion':data.get('champion'),
                'position':data.get('position'), 'requested_position':position,
                'position_inferred':position=='all', 'game_mode':'ranked',
                'patch':((details.get('trends') or {}).get('win') or {}).get('version'),
                'fetched_at':datetime.now(timezone.utc).isoformat(), 'source':ENDPOINT,
                'url':f'https://op.gg/lol/champions/{champion.lower()}/build',
                'data':{k:details[k] for k in ('core_items','starter_items','boots','fourth_items','skills','skill_masteries') if k in details},
                'alternatives':[{'position':p.get('position'),'data':{
                    k:p['data'][k] for k in ('core_items','starter_items','boots','fourth_items','skills','skill_masteries') if k in p['data']}}
                    for p in alternative_data if isinstance(p.get('data',{}).get('core_items'),dict)],
                'rule':'出装统计是参考，非本局购买事实；位置为all时是网站推定位置，未知段位/模式不能假定匹配。版本与国服可能不同。'}
    finally:
        if own:
            await client.aclose()
