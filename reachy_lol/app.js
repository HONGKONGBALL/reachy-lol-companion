const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const token = $('meta[name="demo-token"]').content;
const profiles = {
  velvet: {name:'绯月',gender:'female',desc:'从容低柔 · 有一点气场'},
  sparkle: {name:'铃音',gender:'female',desc:'甜亮轻快 · 元气满格'},
  cedar: {name:'沉舟',gender:'male',desc:'低沉醇厚 · 稳稳接住你'},
  breeze: {name:'星野',gender:'male',desc:'清朗自然 · 少年意气'}
};
const eventMeta={kill:['✦','击杀'],death:['×','阵亡'],multikill:['Ⅱ','连续击杀'],objective:['◆','小龙 / 大龙'],lowhp:['!','低血量'],victory:['✓','胜利']};
const reactions={Hype:'热情欢呼',Supportive:'温柔鼓励','Very excited':'激动喝彩',Happy:'开心回应',Silent:'保持安静',Celebrate:'尽情庆祝'};
const defaults={name:'默默',voice:null,intensity:'normal',volume:.35,input_device:null,output_device:null,seat_yaw:null,events:{kill:{enabled:true,reaction:'Hype'},death:{enabled:true,reaction:'Supportive'},multikill:{enabled:true,reaction:'Very excited'},objective:{enabled:true,reaction:'Happy'},lowhp:{enabled:true,reaction:'Silent'},victory:{enabled:true,reaction:'Celebrate'}}};
let state=structuredClone(defaults), gender=null, saved=null, available={}, runtime=null;
let audioSettingsSupported=false, capabilities={};
let loaded=false, auditionId=null, windowSignature='', saving=false;
let identityView=null, identitySignature='', identityDirty=false;
function renderIdentity(info,force=false){
  $('#refreshIdentity').disabled=!info;
  if(!info){$('#confirmIdentity').disabled=true;$('#identityStatus').textContent='请重启陪玩服务，以启用新版身份确认。';return;}
  $('#reportedIdentityForm').hidden=!capabilities.reported_identity||info.fresh;
  $('#saveReportedIdentity').disabled=!runtime?.running||runtime.paused||runtime.frames<1;
  const changedMatch=identityView?.match_id!==info.match_id;
  identityView=info;
  const owner=info.owner;
  $('#identityStatus').textContent=owner?`${owner.champion||'英雄未知'} · ${owner.team||'阵营未知'} · ${owner.source==='owner_reported'?'主人自报 · 未经接口核实':owner.source==='owner_confirmed'?'主人确认':'接口自动匹配'}`:'身份未确认，暂不指认“你”的战绩';
  $('#confirmIdentity').disabled=!info.fresh;
  const signature=JSON.stringify(info);
  if(!force&&!changedMatch&&(identityDirty||signature===identitySignature))return;
  identityDirty=false;identitySignature=signature;
  $('#ownerIdentity').replaceChildren(new Option('请选择你本局的玩家',''));
  for(const p of info.roster)$('#ownerIdentity').add(new Option(`${p.champion||'未知英雄'} · ${p.name} · ${p.team||'未知阵营'}`,p.name));
  $('#ownerIdentity').value=owner?.name||'';
  renderFriends();
}
function renderFriends(){
  $('#friendIdentities').replaceChildren();
  const owner=identityView?.roster.find(p=>p.name===$('#ownerIdentity').value);
  for(const p of identityView?.roster||[]){
    if(!owner||p.name===owner.name||!owner.team||p.team!==owner.team)continue;
    const row=document.createElement('div');row.className='device-row';
    const label=document.createElement('label');const check=document.createElement('input');check.type='checkbox';check.dataset.friend=p.name;
    const old=identityView.owner?.friends?.find(f=>f.name===p.name);check.checked=!!old;
    label.append(check,document.createTextNode(` ${p.champion||'未知英雄'} · ${p.name}`));
    const nick=document.createElement('input');nick.maxLength=40;nick.placeholder='朋友昵称（可选）';nick.setAttribute('aria-label',`${p.name}的朋友昵称`);nick.value=old?.nickname||'';nick.dataset.nickname=p.name;
    check.onchange=nick.oninput=()=>{identityDirty=true;};row.append(label,nick);$('#friendIdentities').append(row);
  }
}
$('#saveReportedIdentity').onclick=async()=>{try{
  const friends=$('#reportedFriends').value.split('\n').filter(x=>x.trim()).map(line=>{const [nickname,champion,...extra]=line.split('|').map(x=>x.trim());if(extra.length)throw Error('朋友填写格式为“昵称 | 英雄”');return {nickname,champion:champion||null};});
  const result=await api('/api/identity/report',{champion:$('#reportedChampion').value.trim(),team:$('#reportedTeam').value.trim()||null,friends},'PUT');
  renderIdentity(result,true);message('#identityNotice','已记录主人自报，尚未经接口核实；旧归因已撤回。');
}catch(e){message('#identityNotice',e.message,true);}};
$('#ownerIdentity').onchange=()=>{identityDirty=true;renderFriends();};
$('#refreshIdentity').onclick=async()=>{try{renderIdentity(await api('/api/identity/refresh',{}),true);message('#identityNotice','已读取当前对局。请核对自己和组排朋友。');}catch(e){message('#identityNotice',e.message,true);}};
$('#confirmIdentity').onclick=async()=>{try{
  if(!identityView?.fresh)throw Error('请先读取当前对局');
  const friends=$$('[data-friend]').filter(x=>x.checked).map(x=>({name:x.dataset.friend,nickname:$$('[data-nickname]').find(n=>n.dataset.nickname===x.dataset.friend)?.value||''}));
  renderIdentity(await api('/api/identity',{match_id:identityView.match_id,name:$('#ownerIdentity').value,friends},'PUT'),true);
  message('#identityNotice','已确认，本局待播旧判断已撤销。');
}catch(e){message('#identityNotice',e.message,true);}};
function message(selector,text,error=false){const el=$(selector);el.textContent=text;el.classList.toggle('error',error);}
async function api(path,payload,method=payload===undefined?'GET':'POST'){
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Demo-Token':token},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
  const data=await response.json().catch(()=>({detail:`操作失败（HTTP ${response.status}）`}));
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:(data.error||'设置格式不正确'));
  return data;
}
function dirty(){return saved!==JSON.stringify(state);}
function changed(){updatePreview();message('#saved',dirty()?'有未保存的调整':'设置已与本机同步');$('#saved').classList.toggle('setting-dirty',dirty());}
function updatePreview(){const name=state.name.trim()||'默默';$('#previewName').textContent=name;$('#monogram').textContent=Array.from(name)[0];$('#voiceLabel').textContent=profiles[state.voice]?.name||'请选择声线';}
function renderVoices(animate=false){
  $$('[data-gender]').forEach(b=>{const selected=b.dataset.gender===gender;b.setAttribute('aria-pressed',String(selected));b.setAttribute('aria-expanded',String(selected));});
  $('#voicePanel').classList.toggle('open',!!gender);
  $('#voiceGrid').innerHTML=gender?Object.entries(profiles).filter(([,p])=>p.gender===gender).map(([id,p])=>`<div class="voice-card"><input type="radio" name="voice" id="${id}" value="${id}" ${state.voice===id?'checked':''}><label class="voice-inner" for="${id}"><strong>${p.name}</strong><small>${p.desc}</small></label><span class="voice-state">${available[id]?'已配置':'待配置'}</span><button class="audition" data-audition="${id}" aria-label="从本体试听${p.name}">${auditionId===id?'■ 停止试听':'▶ 本体试听'}</button></div>`).join(''):'';
  if(animate){$('#voiceGrid').classList.remove('reveal');void $('#voiceGrid').offsetWidth;$('#voiceGrid').classList.add('reveal');}
  $$('input[name="voice"]').forEach(r=>r.onchange=()=>{stopPreview();state.voice=r.value;changed();});
  $$('[data-audition]').forEach(b=>b.onclick=()=>audition(b.dataset.audition));
  updatePreview();
}
function renderEvents(){
  $('#eventList').innerHTML=Object.entries(eventMeta).map(([key,[icon,label]])=>{const cfg=state.events[key];return `<div class="event-item"><div class="event-name"><span class="event-icon">${icon}</span>${label}</div><select data-reaction="${key}" aria-label="${label}回应方式" ${key==='lowhp'?'disabled':''}>${Object.entries(reactions).map(([id,name])=>`<option value="${id}" ${id===cfg.reaction?'selected':''}>${name}</option>`).join('')}</select><label class="switch"><input type="checkbox" data-toggle="${key}" aria-label="开启${label}" ${cfg.enabled?'checked':''} ${key==='lowhp'?'disabled':''}><span class="switch-track"></span></label></div>`}).join('');
  $$('[data-reaction]').forEach(el=>el.onchange=()=>{state.events[el.dataset.reaction].reaction=el.value;changed();});
  $$('[data-toggle]').forEach(el=>el.onchange=()=>{state.events[el.dataset.toggle].enabled=el.checked;changed();});
}
function renderModes(){ $$('.mode').forEach(b=>{const active=b.dataset.mode===state.intensity;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}); }
function sync(){ $('#seatYaw').value=state.seat_yaw??0;$('#seatYawValue').textContent=state.seat_yaw===null?'尚未设置':state.seat_yaw+'°';$('#robotName').value=state.name;$('#voiceVolume').value=Math.round(state.volume*100);$('#volumeValue').textContent=Math.round(state.volume*100)+'%';renderAudioDevices();renderVoices();renderEvents();renderModes();updatePreview(); }
async function loadPreferences(){
  const data=await api('/api/preferences');
  capabilities=data.capabilities||{};$('#seatSettings').hidden=!capabilities.seat;$('#clearDataSection').hidden=!capabilities.clear_data;
  audioSettingsSupported=Object.hasOwn(data.preferences,'volume');
  $('#voiceVolume').disabled=!audioSettingsSupported;$('#saveDevices').disabled=!audioSettingsSupported;
  state={...structuredClone(defaults),...data.preferences,events:{...structuredClone(defaults.events),...data.preferences.events}};
  available=data.voice_available;gender=profiles[state.voice]?.gender||null;saved=JSON.stringify(state);loaded=true;sync();changed();
}
async function savePreferences(){
  if(!loaded)throw Error('尚未读到后端设置，请刷新页面重试');
  if(saving)throw Error('设置正在保存，请稍候');
  const initial=JSON.stringify(state);const payload=structuredClone(state);payload.name=payload.name.trim()||'默默';
  if(!capabilities.seat)delete payload.seat_yaw;
  if(!audioSettingsSupported)for(const key of ['volume','input_device','output_device'])delete payload[key];
  saving=true;$('#save').disabled=true;
  try{const data=await api('/api/preferences',payload,'PUT');const normalized={...structuredClone(defaults),...data.preferences};saved=JSON.stringify(normalized);available=data.voice_available;if(JSON.stringify(state)===initial){state=normalized;$('#robotName').value=state.name;}changed();message('#saved',dirty()?'上一版已保存，还有新的调整':'✓ 已保存到本机');$('#saved').classList.add('show');return data;}
  finally{saving=false;$('#save').disabled=false;}
}
async function stopPreview(){if(auditionId){auditionId=null;try{await api('/api/control',{action:'stop'});}catch(e){message('#voiceNotice',e.message,true);}renderVoices();}}
async function audition(id){
  if(auditionId===id)return stopPreview();
  await stopPreview();state.voice=id;gender=profiles[id].gender;changed();renderVoices();
  if(!available[id]){message('#voiceNotice','这条声线还未配置。可以先选择并保存，在“设备与连接”中完成模型配置后试听。');return;}
  if(runtime?.running){message('#voiceNotice','请先结束陪玩，再从本体试听，避免打断正在进行的对局。');return;}
  auditionId=id;renderVoices();message('#voiceNotice','正在合成试听音频，稍后从 Reachy 本体播放…');
  try{const result=await api('/api/audition/'+id,{});message('#voiceNotice',result.status==='interrupted'?'试听已停止':'试听音频已写入 Reachy，请确认本体是否发声。');}
  catch(e){message('#voiceNotice',e.message,true);}
  finally{if(auditionId===id)auditionId=null;renderVoices();}
}
async function control(action,value=null){await api('/api/control',{action,value});await refresh();}
async function sessionAction(action){try{await control(action);message('#sessionNotice',action==='end'?'本次陪玩已结束，临时上下文已清空。':action==='pause'?'已暂停游戏画面和麦克风采集，可在这里恢复。':action==='quiet'?'我会继续观察和收听，暂时不主动插话。':action==='resume'?'已恢复采集，等待安全空隙。':'已更新陪玩状态。');}catch(e){message('#sessionNotice',e.message,true);}}
function configureDialog(dialog,open,close,done){$(open).onclick=()=>dialog.showModal();$(close).onclick=$(done).onclick=()=>dialog.close();dialog.onclick=e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}};}
configureDialog($('#reactionDialog'),'#openSettings','#closeSettings','#doneSettings');
configureDialog($('#deviceDialog'),'#openDevices','#closeDevices','#doneDevices');
function renderAudioDevices(){
  for(const [direction,channels] of [['input','inputs'],['output','outputs']]){
    const select=$('#'+direction+'Device'), key=state[direction+'_device'];
    const devices=(runtime?.devices||[]).filter(d=>d[channels]>0);
    const signature=JSON.stringify([devices,key]);
    if(select.dataset.signature!==signature){
      select.dataset.signature=signature;select.replaceChildren(new Option('自动选择 Reachy Audio',''));
      for(const d of devices)select.add(new Option(`${d.name} · ${d.host}`,d.key));
      if(key&&!devices.some(d=>d.key===key))select.add(new Option('已保存设备当前离线',key));
      select.value=key||'';
    }
    select.disabled=!audioSettingsSupported||!!runtime?.running;
  }
}
$('#seatYaw').oninput=e=>{$('#seatYawValue').textContent=e.target.value+'°（待调整）';};
$('#saveSeat').onclick=async()=>{const button=$('#saveSeat');try{
  button.disabled=true;message('#deviceNotice','正在缓慢调整朝向，可点击立即停止…');
  const result=await api('/api/seat',{yaw:Number($('#seatYaw').value)});
  state.seat_yaw=result.preferences.seat_yaw;saved=JSON.stringify({...structuredClone(defaults),...result.preferences});
  $('#seatYawValue').textContent=state.seat_yaw+'°';changed();message('#deviceNotice','朝向已到达并保存。请确认机器人朝向你的座位。');
}catch(e){message('#deviceNotice',e.message,true);}finally{button.disabled=false;}};
$('#clearLocalData').onclick=async()=>{if(!confirm('结束陪玩并永久清除本地会话缓存、用量和运行日志？基础设置保留；独立验收文件和云端记录不受影响。'))return;
  try{const result=await api('/api/data/clear',{});await refresh();message('#deviceNotice',result.cleared?'本地会话与运行记录已清除。':'清除未完成');}catch(e){message('#deviceNotice',e.message,true);}};
$('#voiceVolume').oninput=e=>{state.volume=Number(e.target.value)/100;$('#volumeValue').textContent=e.target.value+'%';changed();};
for(const direction of ['input','output'])$('#'+direction+'Device').onchange=e=>{state[direction+'_device']=e.target.value||null;changed();};
$('#saveDevices').onclick=async()=>{try{await savePreferences();message('#deviceNotice','本体音频设置已保存。');}catch(e){message('#deviceNotice',e.message,true);}};
$('#robotName').oninput=e=>{state.name=e.target.value;changed();};
$$('[data-gender]').forEach(b=>b.onclick=()=>{stopPreview();gender=b.dataset.gender;if(profiles[state.voice]?.gender!==gender)state.voice=Object.keys(profiles).find(k=>profiles[k].gender===gender);renderVoices(true);changed();});
$$('.mode').forEach(b=>b.onclick=()=>{state.intensity=b.dataset.mode;renderModes();changed();});
$('#save').onclick=async()=>{try{await savePreferences();}catch(e){message('#saved',e.message,true);}};
$('#reset').onclick=()=>{stopPreview();state={...structuredClone(defaults),seat_yaw:state.seat_yaw};gender=null;sync();changed();message('#saved','已恢复默认，保存后生效');};
$('#startSession').onclick=async()=>{
  try{
    if(dirty())await savePreferences();
    await control('start');message('#sessionNotice',Object.values(runtime.cloud_configured).every(Boolean)?'麦克风已开启，直接和搭子说话即可。未开局也能聊天；进入对局后自动接入游戏画面。':'陪伴已开始，模型尚未全部配置，暂时无法进行语音理解与回应。');
  }catch(e){message('#sessionNotice',e.message,true);}
};
$('#quietSession').onclick=()=>sessionAction(runtime?.quiet?'unquiet':'quiet');
$('#pauseSession').onclick=()=>sessionAction(runtime?.paused?'resume':'pause');
$('#endSession').onclick=()=>sessionAction('end');
$('#selectWindow').onclick=async()=>{try{const value=$('#gameWindow').value;if(!value)throw Error('尚未发现 LOL 窗口，请先进入游戏。');await control('window',Number(value));message('#deviceNotice','游戏窗口已选择。切回游戏后即可采集。');}catch(e){message('#deviceNotice',e.message,true);}};
$('#stopOutput').onclick=async()=>{try{await control('stop');auditionId=null;renderVoices();message('#deviceNotice','声音与动作已停止。');}catch(e){message('#deviceNotice',e.message,true);}};
$$('[data-diagnostic]').forEach(b=>b.onclick=async()=>{const kind=b.dataset.diagnostic;try{b.disabled=true;message('#deviceNotice',kind==='microphone'?'正在读取本体麦克风，持续 3 秒…':'正在运行本体检查…');const r=await api('/api/diagnostic/'+kind,{});message('#deviceNotice',kind==='microphone'?`本体收音完成：${r.frames.toLocaleString()} 个采样，信号幅度 ${r.rms.toFixed(4)}。语音内容尚未识别。`:kind==='motion'?'小幅动作指令已执行，请确认 Reachy 是否点头。':r.status==='interrupted'?'本体播放已停止。':'语音已写入本体设备，请确认是否听到声音。');await refresh();}catch(e){message('#deviceNotice',e.message,true);}finally{b.disabled=false;}});
$('#reloadConfig').onclick=async()=>{try{await api('/api/reload-config',{});const data=await api('/api/preferences');available=data.voice_available;renderVoices();await refresh();message('#deviceNotice','已重新读取本地配置。');}catch(e){message('#deviceNotice',e.message,true);}};
$('#connectRobot').onclick=async()=>{const b=$('#connectRobot');try{b.disabled=true;message('#deviceNotice','正在连接本体并释放摄像头资源…');await control('connect');message('#deviceNotice','本体已连接，摄像头关闭。可以测试声音与动作。');}catch(e){message('#deviceNotice',e.message,true);}finally{b.disabled=false;}};
async function refresh(){
  try{
    const s=await api('/api/state');runtime=s;renderAudioDevices();$('#seatYaw').disabled=s.running;
    renderIdentity(s.identity_status);
    const ready=s.state.robot.startsWith('实机已连接');
    $('#connectionDot').classList.toggle('off',!ready);$('#connectionText').textContent=ready?'Reachy 已连接':'Reachy 未就绪';$('#cameraState').textContent=ready?'已关闭':'等待服务确认';
    const label=!s.running?'安静待命':s.paused?'已暂停':s.playing?'正在回应':s.quiet?'安静陪伴':s.game_present===false?'正在听你说':'陪玩中';
    $('#liveLabel').textContent=label;$('#moodLabel').textContent=s.playing?(auditionId?'正在试听':'正在回应'):label;$('#livePill').classList.toggle('off',!s.running&&!s.playing);$('#presence').dataset.mood=s.playing?'hype':'idle';
    $('#sessionState').textContent=s.running?s.gate:'尚未开始';$('#captureState').textContent=s.frames>0?`已缓存 ${s.frames} 帧`:s.game_present===false?'未开局 · 可以聊天':s.selected_window?'窗口已选择':'开局后自动接入';
    $('#readiness').textContent=!ready?'本体未就绪，请检查设备与连接':!Object.values(s.cloud_configured).every(Boolean)?'模型配置待完成':s.running?(s.paused?'采集已暂停':s.game_present===false?(s.state.dialogue||'麦克风已开启，可以直接说话'):s.state.vision_safety||s.state.cloud):'可以开始陪伴，未开局也能聊天';
    $('#lastHeard').textContent=s.state.last_heard?'刚才听到：'+s.state.last_heard:'尚未识别到本次对话';
    $('#startSession').disabled=s.running||!ready;$('#startSession').textContent=s.running?'正在陪你':'开始陪伴';
    for(const id of ['quietSession','pauseSession','endSession'])$('#'+id).disabled=!s.running;
    $('#quietSession').textContent=s.quiet?'恢复回应':'安静陪着';$('#pauseSession').textContent=s.paused?'恢复采集':'暂停采集';
    const names={robot:'Reachy 连接',microphone:'本体麦克风',speaker:'本体扬声器',motion:'本体动作',capture:'游戏画面',game_api:'国服只读接口',vision_safety:'发言时机检查',match_research:'本局阵容与外号资料',equipment_memory:'长期装备记忆',build_research:'本局出装攻略',expression_skills:'情绪动作预设'};
    $('#deviceGrid').replaceChildren();for(const [k,name] of Object.entries(names)){const value=s.state[k]||'等待检查';const box=document.createElement('div');box.className='device-item';box.dataset.ready=String(k==='robot'?ready:value.includes('已')||value.includes('真实'));const title=document.createElement('b');title.textContent=name;const description=document.createElement('span');description.textContent=value;box.append(title,description);$('#deviceGrid').append(box);}
    const signature=JSON.stringify(s.windows);if(signature!==windowSignature){const selected=$('#gameWindow').value;windowSignature=signature;$('#gameWindow').replaceChildren();const games=s.windows.filter(w=>w.is_game);if(!games.length)$('#gameWindow').add(new Option(s.windows.length?'当前只有大厅，请先进入对局':'尚未发现英雄联盟窗口',''));for(const w of games)$('#gameWindow').add(new Option(w.title,w.hwnd));if(games.some(w=>String(w.hwnd)===selected))$('#gameWindow').value=selected;}
    const modelNames={vision:'画面理解',chat:'对话',asr:'语音识别',tts:'语音合成'};
    $('#cloudSummary').textContent=Object.entries(s.cloud_configured).map(([k,v])=>`${modelNames[k]}：${v?'已配置':'未配置'}`).join(' · ')+'。在本地 .env 分别填写 VISION / CHAT / ASR / TTS 的 BASE_URL、API_KEY 和 MODEL，可接不同平台。每组地址和密钥都留空时沿用公共配置。四条声线对应 VOICE_VELVET / VOICE_SPARKLE / VOICE_CEDAR / VOICE_BREEZE，支持系统或授权定制音色。配置检测通过不代表接口调用已验证。';
  }catch(e){runtime=null;$('#connectionText').textContent='本地服务未连接';$('#connectionDot').classList.add('off');$('#cameraState').textContent='状态未知';$('#readiness').textContent='服务连接中断';$('#startSession').disabled=true;message('#sessionNotice','本地服务连接中断，请重新运行 start.ps1 或刷新页面。',true);}
}
async function init(){sync();try{await loadPreferences();}catch(e){message('#saved','无法读取设置：'+e.message,true);$('#save').disabled=true;}await refresh();}
init();setInterval(refresh,1500);
