// Offline control-flow checks; these do not render or replace real Chrome testing.
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../extension/app.js'),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function run(token,offline=false){
  const nodes=new Map(),calls=[],stored={unscrollToken:token},handlers={};
  const node=id=>{
    if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,open:false,
      events:{},addEventListener(type,fn){this.events[type]=fn;},
      showModal(){this.open=true;},close(){this.open=false;}});
    return nodes.get(id);
  };
  const data={counts:{total:0,ready:0,reviewed:0},tree:[],jobs:[],job_counts:{},creators:[],usage:{},paused:true};
  const context={console,URLSearchParams,FormData,URL,structuredClone,
    confirm:()=>false,
    location:{protocol:'chrome-extension:'},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(type,fn){handlers[type]=fn;},hidden:false},
    chrome:{storage:{local:{get:async()=>stored,set:async values=>Object.assign(stored,values)}}},
    setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},
    fetch:async(url,opts)=>{
      calls.push({url,opts});if(offline)throw new Error('offline');
      const result=url.endsWith('/imports/remove-preview')?{ids:['123','456'],count:2}:
        url.endsWith('/imports/remove')?{removed:2,message:'Removed two posts.'}:
        url.endsWith('/imports/undo')?{message:'Restored two posts.'}:
        url.includes('/session')?{token:'valid-token',api_ready:true,tools:{},model:'test-model'}:
        url.includes('/state')?data:{posts:[],warning:''};
      return {ok:true,json:async()=>result};
    }};
  vm.runInNewContext(source,context);await tick();await tick();
  return {node,calls,stored,context,click:async id=>{
    const button={id,dataset:{},hasAttribute:()=>false};
    await handlers.click({target:{closest:()=>button}});
  }};
}
(async()=>{
  let app=await run('');
  assert.equal(app.node('#connect-dialog').open,true);assert.equal(app.calls.length,0);
  app.node('#pairing-token').value='valid-token';
  await app.node('#connect-helper').events.click();await tick();
  assert.equal(app.stored.unscrollToken,'valid-token');assert(app.calls.length>=3);
  assert.equal(app.node('#connect-dialog').open,false);
  assert(app.calls.every(c=>c.url.startsWith('http://127.0.0.1:8765/api/')));
  assert(app.calls.every(c=>c.opts.headers['X-Unscroll-Token']==='valid-token'));
  app=await run('valid-token',true);
  assert.equal(app.node('#connect-dialog').open,true);
  assert.match(app.node('#connection-error').textContent,/helper is not running/);
  app=await run('valid-token');
  assert.equal(app.node('#connect-dialog').open,false);assert(app.calls.length>=3);
  await app.click('remove-unprocessed');
  assert(app.calls.some(c=>c.url.endsWith('/imports/remove-preview')));
  assert(!app.calls.some(c=>c.url.endsWith('/imports/remove')));
  app.context.confirm=()=>true;
  await app.click('remove-unprocessed');
  const removal=app.calls.find(c=>c.url.endsWith('/imports/remove'));
  assert.deepEqual(JSON.parse(removal.opts.body),{ids:['123','456']});
  vm.runInNewContext('state.selected.add("123")',app.context);
  let confirmation='';app.context.confirm=message=>{confirmation=message;return true;};
  await app.click('remove-selected');
  const selectedRemoval=app.calls.filter(c=>c.url.endsWith('/imports/remove')).at(-1);
  assert.deepEqual(JSON.parse(selectedRemoval.opts.body),{ids:['123','456'],include_processed:true});
  assert.match(confirmation,/completed entries and category placements/);
  assert.match(confirmation,/Downloaded files stay on disk/);
  await app.click('undo-removal');
  assert(app.calls.some(c=>c.url.endsWith('/imports/undo')));
  console.log('Extension boot checks passed: unpaired, pairing, paired API routing and helper unavailable.');
})().catch(e=>{console.error(e);process.exit(1);});
