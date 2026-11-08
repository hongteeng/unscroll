// Offline popup workflow checks; real TikTok scrolling still needs Chrome testing.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../extension/popup.js'), 'utf8');
const post = id => ({id:String(id), url:`https://www.tiktok.com/@tester/video/${id}`});
const key = 'unscrollProgressV2:'+JSON.stringify(['https://www.tiktok.com/@tester/favorites','test-scope','']);

async function setup({known=[], saved, pages=[[1]], fail=false, stop=false,scanError=''}={}) {
  const nodes = new Map(), stored = {unscrollToken:'token'}, actions=[], imports=[];
  if(saved) stored[key]=saved;
  const node=id=>{
    if(!nodes.has(id)) nodes.set(id,{value:'',disabled:false,hidden:false,textContent:'',events:{},
      addEventListener(type, fn){this.events[type]=fn;}});
    return nodes.get(id);
  };
  let index=0;
  const context={URL, console, confirm:()=>true,document:{getElementById:node},
    chrome:{storage:{local:{get:async()=>({...stored}),set:async v=>Object.assign(stored,v)}},
      tabs:{query:async()=>[{id:1,url:'https://www.tiktok.com/@tester/favorites'}]},
      scripting:{executeScript:async ({args})=>{
        const action=args[0];if(action!=='inspect')actions.push(action);
        if(scanError)return [{result:{error:scanError}}];
        if(action==='top')index=0;
        if(action==='down')index=Math.min(index+1,pages.length-1);
        const ids=pages[index];
        return [{result:{posts:ids.map(post),y:index*800,scope:'test-scope',anchorFound:action==='resume'&&ids.includes(Number(saved?.id))}}];
      }}},
    fetch:async(url,opts)=>{
      if(url.endsWith('/posts'))return {ok:true,json:async()=>({posts:known.map(post)})};
      const batch=JSON.parse(opts.body).posts;imports.push(batch);
      if(stop)node('stop').events.click();
      return {ok:!fail,json:async()=>fail?{detail:'Helper rejected batch'}:{added:batch.filter(p=>!known.includes(Number(p.id))).length,enriched:0,errors:[]}};
    }};
  vm.runInNewContext(source,context);
  await new Promise(r=>setImmediate(r));
  return {node,stored,actions,imports,context,run:mode=>node(mode).events.click()};
}

(async()=>{
  // Quick checks import new posts, stop at old posts, and preserve backlog progress.
  let app=await setup({known:[1,2,3,4],saved:{id:'99',y:1000},pages:[[5],[1],[2],[3],[4]]});
  await app.run('check');
  assert.deepEqual(app.imports.flat().map(p=>p.id),['5']);
  assert.equal(app.stored[key].id,'99');
  assert.equal(app.actions.filter(a=>a==='down').length,3);
  assert.match(app.node('status').textContent,/already imported/);

  // A bookmark on a loaded page resumes directly, without starting at the top.
  app=await setup({known:[1],saved:{id:'1',y:800},pages:[[1],[2]]});
  await app.run('continue');
  assert.equal(app.actions[0],'resume');assert(!app.actions.includes('top'));
  assert.equal(app.stored[key].id,'2');
  assert.deepEqual(app.imports.flat().map(p=>p.id),['2']);

  // Reopened/virtualized pages can seek the previous post before advancing.
  app=await setup({known:[1,2],saved:{id:'2',y:800},pages:[[1],[2],[3]]});
  await app.run('continue');
  assert.deepEqual(app.actions.slice(0,3),['resume','top','down']);
  assert.deepEqual(app.imports.flat().map(p=>p.id),['3']);

  // A missing bookmark must not silently skip posts or replace saved progress.
  app=await setup({saved:{id:'99',y:800},pages:[[1],[2]]});
  await app.run('continue');
  assert.equal(app.imports.length,0);assert.equal(app.stored[key].id,'99');
  assert.match(app.node('status').textContent,/Could not find your last imported post/);

  // Explicit rescans send known posts again to refresh metadata.
  app=await setup({known:[1],pages:[[1],[2]]});await app.run('rescan');
  assert.deepEqual(app.imports.flat().map(p=>p.id),['1','2']);
  assert.equal(app.actions[0],'top');

  // Failed imports never advance the durable bookmark; controls recover.
  app=await setup({saved:{id:'99',y:800},fail:true});await app.run('rescan');
  assert.equal(app.stored[key].id,'99');assert.equal(app.node('check').disabled,false);
  assert.match(app.node('status').textContent,/Helper rejected batch/);

  app=await setup({stop:true,pages:[[1],[2]]});await app.run('continue');
  assert.equal(app.stored[key].id,'1');assert.equal(app.actions.length,1);
  assert.match(app.node('status').textContent,/Stopped/);
  app=await setup();app.context.confirm=()=>false;await app.run('rescan');
  assert.equal(app.imports.length,0);assert.equal(app.actions.length,0);
  app=await setup({scanError:'Choose the collection on the TikTok page first. No posts imported.'});
  await app.run('check');
  assert.equal(app.imports.length,0);
  assert.match(app.node('status').textContent,/^Choose the collection/);
  assert.doesNotMatch(app.node('status').textContent,/0 posts found/);
  app=await setup({known:[],pages:[[1],[2]]});await app.run('check');
  assert.deepEqual(app.imports.flat().map(p=>p.id),['1','2']);
  console.log('Popup import checks passed: quick check, resume, seek, missing bookmark, rescan, failure, stop.');
})().catch(e=>{console.error(e);process.exit(1);});
