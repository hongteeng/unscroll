const el=id=>document.getElementById(id);
chrome.storage.local.get(['unscrollToken','siftToken']).then(r=>el('token').value=r.unscrollToken||r.siftToken||'');
el('open-library').addEventListener('click',async()=>{
  const token=el('token').value.trim();
  if(token)await chrome.storage.local.set({unscrollToken:token});
  const url=chrome.runtime.getURL('library.html');
  let tabs=[];
  try{tabs=await chrome.tabs.query({url});}catch{}
  if(tabs.length)await chrome.tabs.update(tabs[0].id,{active:true});
  else await chrome.tabs.create({url});
});
// This function runs in the TikTok tab and must not use popup variables.
async function captureInPage(action,collection,page,checkpoint){
  if(location.origin+location.pathname+location.search+location.hash!==page)throw new Error('The TikTok page changed. Open the popup again on the collection you want.');
  const wait=()=>new Promise(r=>setTimeout(r,1600));
  if(action==='top'){window.scrollTo(0,0);await wait();}
  if(action==='down'){window.scrollBy(0,Math.max(500,window.innerHeight*.85));await wait();}
  let anchorFound=false;
  if(action==='resume'){
    window.scrollTo(0,checkpoint.y||0);await wait();
    const anchor=[...document.querySelectorAll('a[href]')].find(a=>a.href.match(/\/(?:video|photo)\/(\d+)/)?.[1]===checkpoint.id);
    if(anchor){anchor.scrollIntoView();anchorFound=true;await wait();}
  }
  const posts=new Map();
  const add=url=>{
    try{const u=new URL(url,location.href);const m=u.pathname.match(/\/(video|photo)\/(\d+)/);if(u.hostname.endsWith('.tiktok.com')&&m&&!posts.has(m[2]))posts.set(m[2],{url:u.origin+u.pathname,collections:collection?[collection]:[]});}catch{}
  };
  function scan(){
    document.querySelectorAll('a[href]').forEach(a=>add(a.href));
    add(location.href);
    const walk=(x,depth=0)=>{
      if(depth>30||!x||typeof x!=='object')return;
      if(x.id&&posts.has(String(x.id))){
        const p=posts.get(String(x.id));
        if(typeof x.desc==='string')p.caption=x.desc;
        if(x.author?.uniqueId)p.creator=x.author.uniqueId;
        if(x.createTime)p.posted_date=new Date(Number(x.createTime)*1000).toISOString().slice(0,10);
        if(x.video?.cover)p.thumbnail=x.video.cover;
        if(Array.isArray(x.textExtra))p.hashtags=x.textExtra.map(t=>t.hashtagName).filter(Boolean);
        const images=x.imagePost?.images;
        if(Array.isArray(images)&&images.length){
          const urls=images.map(i=>(i.imageURL?.urlList||i.imageURL?.url_list||[])[0]);
          if(urls.every(Boolean)){p.slides=urls;p.slide_count=images.length;p.slides_complete=true;}
        }
      }
      (Array.isArray(x)?x:Object.values(x)).forEach(v=>walk(v,depth+1));
    };
    for(const id of ['__UNIVERSAL_DATA_FOR_REHYDRATION__','SIGI_STATE']){
      try{walk(JSON.parse(document.getElementById(id)?.textContent||'null'));}catch{}
    }
  }
  scan();
  const rows=[...posts.values()];
  return {posts:rows,y:window.scrollY,anchorFound};
}
let stopped=false;
const buttons=['check','continue','rescan'];
const postId=p=>p.url.match(/\/(?:video|photo)\/(\d+)/)?.[1];
async function run(mode){
  buttons.forEach(id=>el(id).disabled=true);
  el('token').disabled=el('collection').disabled=true;
  el('stop').hidden=false;el('stop').disabled=false;stopped=false;
  let added=0,updated=0,found=new Set();
  const counts=()=>`${found.size} posts found · ${added} new · ${updated} updated`;
  try{
    const token=el('token').value.trim();
    if(!token)throw new Error('Paste the pairing token from Unscroll Settings first.');
    await chrome.storage.local.set({unscrollToken:token});
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const u=new URL(tab.url||'');
    if(u.protocol!=='https:'||!(u.hostname==='www.tiktok.com'||u.hostname==='tiktok.com'))throw new Error('Open your Favorites or a post on www.tiktok.com first.');
    const collection=el('collection').value.trim();
    const page=u.origin+u.pathname+u.search+u.hash;
    const key='unscrollProgress:'+JSON.stringify([page,collection]);
    const saved=(await chrome.storage.local.get(key))[key];
    const headers={'Content-Type':'application/json','X-Unscroll-Token':token};
    const api=async(path,body)=>{
      const r=await fetch('http://127.0.0.1:8765/api/'+path,{headers,...(body?{method:'POST',body:JSON.stringify(body)}:{})});
      const data=await r.json();if(!r.ok)throw new Error(data.detail||'Import failed.');return data;
    };
    // Ask the helper, so existing libraries and imports made elsewhere count too.
    const known=new Set((await api('posts')).posts.map(p=>String(p.id)));
    const step=async(action)=>{
      const [result]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureInPage,args:[action,collection,page,saved||null]});
      if(!result?.result)throw new Error('Could not read this TikTok page. Reopen Favorites and try again.');
      return result.result;
    };
    let batch;
    if(mode==='continue'&&saved?.id){
      el('status').textContent='Returning to your last imported post…';
      batch=await step('resume');
      if(!batch.anchorFound){
        el('status').textContent='TikTok unloaded your last position. Finding your last imported post…';
        batch=await step('top');
        let idle=0,previous='';
        for(let i=0;i<200&&!stopped&&!batch.posts.some(p=>postId(p)===saved.id);i++){
          const signature=batch.posts.map(postId).join(',');
          idle=signature===previous?idle+1:0;previous=signature;
          if(idle>=6)break;
          batch=await step('down');
        }
        if(stopped){el('status').textContent='Stopped. Your previous import position is preserved.';return;}
        if(!batch.posts.some(p=>postId(p)===saved.id))throw new Error('Could not find your last imported post. It may have moved or been removed. Use Rescan everything to rebuild progress.');
      }
    }else{
      el('status').textContent=mode==='check'?'Checking the top of your saves…':'Starting at the top of your saves…';
      batch=await step('top');
    }
    let idle=0,knownStretch=0,reason='Import limit reached. Choose Continue importing older saves to carry on.';
    for(let i=0;i<200&&!stopped;i++){
      const fresh=batch.posts.filter(p=>!found.has(postId(p)));
      const alreadyKnown=fresh.length>0&&fresh.every(p=>known.has(postId(p)));
      // Rescans deliberately refresh metadata; other modes submit only new posts.
      const pending=mode==='rescan'?fresh:fresh.filter(p=>!known.has(postId(p)));
      if(pending.length){
        const data=await api('capture',{posts:pending});
        if(data.errors?.length)throw new Error(data.errors.join(' '));
        added+=data.added;updated+=data.enriched;
        pending.forEach(p=>known.add(postId(p)));
      }
      fresh.forEach(p=>found.add(postId(p)));
      // A quick check never overwrites the older-import bookmark.
      if(mode!=='check'&&batch.posts.length){
        await chrome.storage.local.set({[key]:{id:postId(batch.posts.at(-1)),y:batch.y}});
      }
      idle=fresh.length?0:idle+1;
      knownStretch=alreadyKnown?knownStretch+1:(fresh.length?0:knownStretch);
      el('status').textContent=`${counts()}. ${mode==='check'?'Checking for new saves…':'Importing older saves…'}`;
      if(mode==='check'&&knownStretch>=3){reason='Reached a stretch of already imported posts. Use Continue importing older saves for your backlog, or Rescan everything to check for gaps.';break;}
      if(idle>=6){reason='No more posts loaded. TikTok may still have more saves.';break;}
      if(stopped)break;
      batch=await step('down');
    }
    if(!found.size&&!stopped)throw new Error('No full post links found. Open Favorites and let the grid load.');
    el('status').textContent=`${counts()}. ${stopped?'Stopped.':reason} Open your library to process new posts.`;
  }catch(e){el('status').textContent=`${counts()}. `+(e.message==='Failed to fetch'?'Could not reach Unscroll. Start the local helper and try again.':e.message);}
  finally{
    buttons.forEach(id=>el(id).disabled=false);
    el('token').disabled=el('collection').disabled=false;el('stop').hidden=true;
  }
}
el('check').addEventListener('click',()=>run('check'));
el('continue').addEventListener('click',()=>run('continue'));
el('rescan').addEventListener('click',()=>run('rescan'));
el('stop').addEventListener('click',()=>{stopped=true;el('stop').disabled=true;el('status').textContent='Stopping after the current batch…';});
