// Frontend behavior test: real click handlers and fetch payloads, no browser/hardware.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

async function fixture(){
  function element(dataset={}){
    const classes=new Set();
    return {dataset,disabled:false,content:'test-token',value:'',textContent:'',innerHTML:'',
      classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),
        toggle:(x,on)=>on?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},
      setAttribute(){},replaceChildren(){},add(){},append(){}};
  }
  const nodes=new Map(),modes=['chill','normal','chaos'].map(mode=>element({mode}));
  const get=s=>{if(!nodes.has(s))nodes.set(s,element());return nodes.get(s);};
  const prefs={name:'默默',voice:null,intensity:'chaos',volume:.35,seat_yaw:null};
  const calls=[];let onPut;
  const state={running:true,paused:false,quiet:true,intensity:'chaos',state:{robot:'实机已连接'},
    cloud_configured:{},windows:[],devices:[],frames:0};
  const response=(body,ok=true)=>({ok,status:ok?200:500,json:async()=>body});
  const context=vm.createContext({structuredClone,console,Option:function(){},setInterval(){},
    document:{querySelector:get,querySelectorAll:s=>s==='.mode'?modes:[],createElement:()=>element()},
    fetch:async(url,options)=>{
      calls.push({url,...options});
      if(url==='/api/intensity')return onPut(JSON.parse(options.body));
      if(url==='/api/preferences')return response({preferences:prefs,voice_available:{},capabilities:{live_intensity:true}});
      if(url==='/api/state')return response(state);
      throw Error(url);
    }});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../reachy_lol/app.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  return {context,modes,get,calls,state,response,setPut:fn=>onPut=fn};
}

test('click sends only mode; selection waits for server and preserves unsaved name',async()=>{
  const f=await fixture();let resolve;
  f.setPut(()=>new Promise(r=>resolve=r));
  vm.runInContext("state.name='未保存的新名字'",f.context);
  const promise=f.modes[1].onclick();
  assert.equal(f.calls.at(-1).url,'/api/intensity');
  assert.equal(f.calls.at(-1).method,'PUT');
  assert.deepEqual(JSON.parse(f.calls.at(-1).body),{intensity:'normal'});
  assert.equal(f.modes[2].classList.contains('active'),true);
  assert.equal(f.modes[1].classList.contains('active'),false);
  f.state.intensity='normal';f.state.quiet=false;
  resolve(f.response({behavior:{intensity:'normal',quiet:false}}));await promise;
  assert.equal(f.modes[1].classList.contains('active'),true);
  assert.equal(vm.runInContext('state.name',f.context),'未保存的新名字');
  assert.equal(vm.runInContext('JSON.parse(saved).name',f.context),'默默');
});

test('failed backend request leaves the confirmed selection and displays failure',async()=>{
  const f=await fixture();f.setPut(async()=>f.response({detail:'disk full'},false));
  await f.modes[1].onclick();
  assert.equal(f.modes[2].classList.contains('active'),true);
  assert.match(f.get('#intensityStatus').textContent,/未生效.*disk full/);
  assert.equal(f.modes[1].disabled,false);
});

test('reselecting current loud mode sends request to clear temporary quiet',async()=>{
  const f=await fixture();
  f.setPut(async()=>{f.state.quiet=false;return f.response({behavior:{intensity:'chaos',quiet:false}});});
  await f.modes[2].onclick();
  assert.equal(f.calls.filter(c=>c.url==='/api/intensity').length,1);
  assert.equal(vm.runInContext('runtime.quiet',f.context),false);
});
