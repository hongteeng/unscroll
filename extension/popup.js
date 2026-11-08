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
function chooseCollectionInPage(){
  globalThis.__unscrollPickerCleanup?.();
  delete globalThis.__unscrollScope;
  const notice=document.createElement('div');
  notice.textContent='Unscroll: click a video tile INSIDE the collection you want. Escape cancels.';
  notice.style.cssText='position:fixed;top:12px;left:12px;z-index:2147483647;background:#294e3f;color:white;padding:18px;border-radius:8px;font:16px sans-serif;pointer-events:none';
  document.documentElement.append(notice);
  const cleanup=()=>{document.removeEventListener('click',pick,true);document.removeEventListener('keydown',cancel,true);notice.remove();delete globalThis.__unscrollPickerCleanup;};
  const cancel=e=>{if(e.key==='Escape')cleanup();};
  const pick=e=>{
    // Supported TikTok grids only. Never fall back to document/main/body.
    const root=e.target.closest('[data-e2e="user-post-item-list"], [data-e2e="user-favorite-item-list"], [data-e2e="user-collection-item-list"]');
    const tile=e.target.closest('[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]');
    e.preventDefault();e.stopImmediatePropagation();
    if(!root||!tile||!root.contains(tile)){
      notice.textContent='Unscroll could not identify this video grid. Click a video tile in the open collection, or press Escape. No posts imported.';
      return;
    }
    const shown=node=>{
      for(let p=node;p;p=p.parentElement){
        if(p.hidden||p.getAttribute('aria-hidden')==='true')return false;
        const style=getComputedStyle(p);
        if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse')return false;
      }
      return node.getClientRects().length>0||(getComputedStyle(node).display==='contents'&&[...node.querySelectorAll('*')].some(child=>child.getClientRects().length>0&&getComputedStyle(child).visibility==='visible'));
    };
    const headings=[...document.querySelectorAll('h1,h2,[role="tab"][aria-selected="true"]')].filter(n=>!root.contains(n)&&shown(n)).map(n=>n.textContent.trim());
    const markers=[];
    for(let p=root;p;p=p.parentElement)markers.push([p.id,p.getAttribute('data-collection-id'),p.getAttribute('aria-label')]);
    globalThis.__unscrollScope={root,id:crypto.randomUUID(),page:location.href,identity:JSON.stringify([headings,markers])};
    cleanup();
    const done=document.createElement('div');
    done.textContent='Collection selected. Reopen Unscroll to review the count and import.';
    done.style.cssText=notice.style.cssText;
    document.documentElement.append(done);setTimeout(()=>done.remove(),5000);
  };
  document.addEventListener('click',pick,true);document.addEventListener('keydown',cancel,true);
  globalThis.__unscrollPickerCleanup=cleanup;
}
async function captureInPage(action,collection,page,checkpoint){
  // Return failures explicitly: Chrome may drop rejected injection results.
  try{
  if(location.origin+location.pathname+location.search+location.hash!==page)throw new Error('The TikTok page changed. Open the popup again on the collection you want.');
  const scope=globalThis.__unscrollScope;
  if(!scope||!scope.root.isConnected||scope.page!==location.href)throw new Error('Choose the collection on the TikTok page first. No posts imported.');
  const root=scope.root;
  const visible=node=>{
    for(let p=node;p;p=p.parentElement){
      if(p.hidden||p.getAttribute('aria-hidden')==='true')return false;
      const style=getComputedStyle(p);
      if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse')return false;
    }
    return node.getClientRects().length>0||(getComputedStyle(node).display==='contents'&&[...node.querySelectorAll('*')].some(child=>child.getClientRects().length>0&&getComputedStyle(child).visibility==='visible'));
  };
  const identity=()=>{
    const headings=[...document.querySelectorAll('h1,h2,[role="tab"][aria-selected="true"]')].filter(n=>!root.contains(n)&&visible(n)).map(n=>n.textContent.trim());
    const markers=[];
    for(let p=root;p;p=p.parentElement)markers.push([p.id,p.getAttribute('data-collection-id'),p.getAttribute('aria-label')]);
    return JSON.stringify([headings,markers]);
  };
  const checkScope=()=>{
    if(!root.isConnected||!visible(root)||scope.page!==location.href||(scope.identity&&scope.identity!==identity()))throw new Error('The selected collection changed or closed. Choose the collection again before importing.');
  };
  checkScope();scope.identity??=identity();
  if(checkpoint?.scope&&checkpoint.scope!==scope.id)throw new Error('Choose this collection again and start a fresh import.');
  let scroller=root;
  while(scroller!==document.scrollingElement&&scroller.parentElement&&!(scroller.scrollHeight>scroller.clientHeight&&/auto|scroll/.test(getComputedStyle(scroller).overflowY)))scroller=scroller.parentElement;
  if(!scroller.parentElement)scroller=document.scrollingElement;
  const wait=()=>new Promise(r=>setTimeout(r,1600));
  if(action==='top'){scroller.scrollTo(0,0);await wait();}
  if(action==='down'){scroller.scrollBy(0,Math.max(300,scroller.clientHeight*.85));await wait();}
  let anchorFound=false;
  if(action==='resume'){
    scroller.scrollTo(0,checkpoint.y||0);await wait();
    const anchor=[...root.querySelectorAll('a[href]')].find(a=>visible(a)&&a.closest('[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]')?.closest('[data-e2e="user-post-item-list"], [data-e2e="user-favorite-item-list"], [data-e2e="user-collection-item-list"]')===root&&a.href.match(/\/(?:video|photo)\/(\d+)/)?.[1]===checkpoint.id);
    if(anchor){anchor.scrollIntoView();anchorFound=true;await wait();}
  }
  checkScope();
  const posts=new Map();
  const add=url=>{
    try{const u=new URL(url,location.href);const m=u.pathname.match(/^\/@[^/]+\/(video|photo)\/(\d+)\/?$/);if(u.protocol==='https:'&&['www.tiktok.com','tiktok.com'].includes(u.hostname)&&!u.port&&m&&!posts.has(m[2]))posts.set(m[2],{url:u.origin+u.pathname,collections:collection?[collection]:[]});}catch{}
  };
  function scan(){
    root.querySelectorAll('[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]').forEach(tile=>{
      if(!visible(tile)||tile.closest('[data-e2e="user-post-item-list"], [data-e2e="user-favorite-item-list"], [data-e2e="user-collection-item-list"]')!==root)return;
      tile.querySelectorAll('a[href]').forEach(a=>{if(visible(a))add(a.href);});
    });
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
  return {posts:rows,y:scroller.scrollTop,anchorFound,scope:scope.id};
  }catch(error){return {error:error.message||'Could not read the chosen collection. Choose it again on the TikTok page.'};}
}
let stopped=false;
const buttons=['check','continue','rescan'];
const postId=p=>p.url.match(/\/(?:video|photo)\/(\d+)/)?.[1];
async function run(mode){
  buttons.forEach(id=>el(id).disabled=true);
  el('choose-collection').disabled=true;
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
    const inspection=(await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureInPage,args:['inspect',collection,page,null]}))[0]?.result;
    if(inspection?.error)throw new Error(inspection.error);
    if(!inspection)throw new Error('Chrome could not read the collection. Click Choose collection on page, select a video tile, and reopen Unscroll.');
    if(!inspection.posts?.length)throw new Error('The chosen grid contains no supported video links. If videos are visible, this TikTok layout may not be supported. Choose the collection again.');
    const key='unscrollProgressV2:'+JSON.stringify([page,inspection.scope,collection]);
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
      if(result.result.error)throw new Error(result.result.error);
      if(result.result.scope!==inspection.scope)throw new Error('The selected collection changed. Import stopped.');
      return result.result;
    };
    if(!confirm(`Selected grid: ${inspection.posts.length} loaded posts. Import only from this grid? Keep this collection open while importing.`))return;
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
        await chrome.storage.local.set({[key]:{id:postId(batch.posts.at(-1)),y:batch.y,scope:batch.scope}});
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
  }catch(e){el('status').textContent=(found.size?`${counts()}. `:'')+(e.message==='Failed to fetch'?'Could not reach Unscroll. Start the local helper and try again.':e.message);}
  finally{
    buttons.forEach(id=>el(id).disabled=false);
    el('choose-collection').disabled=false;
    el('token').disabled=el('collection').disabled=false;el('stop').hidden=true;
  }
}
el('check').addEventListener('click',()=>run('check'));
el('continue').addEventListener('click',()=>run('continue'));
el('rescan').addEventListener('click',()=>run('rescan'));
el('stop').addEventListener('click',()=>{stopped=true;el('stop').disabled=true;el('status').textContent='Stopping after the current batch…';});
el('choose-collection').addEventListener('click',async()=>{
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const url=new URL(tab.url||'');
    if(url.protocol!=='https:'||!['www.tiktok.com','tiktok.com'].includes(url.hostname))throw new Error('Open the TikTok collection first.');
    await chrome.scripting.executeScript({target:{tabId:tab.id},func:chooseCollectionInPage});
    window.close();
  }catch(e){el('status').textContent=e.message;}
});
