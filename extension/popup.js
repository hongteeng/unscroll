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
async function captureInPage(action,collection,page,checkpoint){
  // Return failures explicitly: Chrome may drop rejected injection results.
  try{
  if(location.origin+location.pathname+location.search+location.hash!==page)throw new Error('The TikTok page changed. Open the popup again on the collection you want.');
  let scope=globalThis.__unscrollScope;
  const visible=node=>{
    for(let p=node;p;p=p.parentElement){
      if(p.hidden||p.getAttribute('aria-hidden')==='true')return false;
      const style=getComputedStyle(p);
      if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse')return false;
    }
    return node.getClientRects().length>0||(getComputedStyle(node).display==='contents'&&[...node.querySelectorAll('*')].some(child=>child.getClientRects().length>0&&getComputedStyle(child).visibility==='visible'));
  };
  // Find the video grid automatically: the whole collection or Favorites page, no clicking.
  if(!scope||!scope.root.isConnected||scope.page!==location.href){
    const KNOWN='[data-e2e="user-post-item-list"], [data-e2e="user-favorite-item-list"], [data-e2e="user-collection-item-list"]';
    const ITEM='[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]';
    const LINK='a[href*="/video/"],a[href*="/photo/"]';
    let found=[...document.querySelectorAll(KNOWN)].filter(visible).sort((x,y)=>y.querySelectorAll(ITEM).length-x.querySelectorAll(ITEM).length)[0]||null;
    let generic=false;
    if(!found||!found.querySelectorAll(ITEM).length){
      found=null;let most=0;
      for(const link of [...document.querySelectorAll(LINK)].filter(visible).slice(0,40)){
        for(let n=link.parentElement;n&&n!==document.body&&n!==document.documentElement;n=n.parentElement){
          if(n.querySelector('h1,nav,header,[role="tablist"]'))break;
          const count=new Set([...n.querySelectorAll(LINK)].map(x=>x.pathname)).size;
          if(count>=3&&count>most){most=count;found=n;generic=true;}
        }
      }
    }
    if(!found)throw new Error('No video grid found on this TikTok page. Open your Favorites or a collection, let the videos load, then try again.');
    scope={root:found,generic,id:'page',page:location.href};
    globalThis.__unscrollScope=scope;
  }
  const root=scope.root;
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
    const inGrid=a=>scope.generic||a.closest('[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]')?.closest('[data-e2e="user-post-item-list"], [data-e2e="user-favorite-item-list"], [data-e2e="user-collection-item-list"]')===root;
    const anchor=[...root.querySelectorAll('a[href]')].find(a=>visible(a)&&inGrid(a)&&a.href.match(/\/(?:video|photo)\/(\d+)/)?.[1]===checkpoint.id);
    if(anchor){anchor.scrollIntoView();anchorFound=true;await wait();}
  }
  checkScope();
  const posts=new Map();
  const add=url=>{
    try{const u=new URL(url,location.href);const m=u.pathname.match(/^\/@[^/]+\/(video|photo)\/(\d+)\/?$/);if(u.protocol==='https:'&&['www.tiktok.com','tiktok.com'].includes(u.hostname)&&!u.port&&m&&!posts.has(m[2]))posts.set(m[2],{url:u.origin+u.pathname,collections:collection?[collection]:[]});}catch{}
  };
  function scan(){
    if(scope.generic)root.querySelectorAll('a[href]').forEach(a=>{if(visible(a))add(a.href);});
    else root.querySelectorAll('[data-e2e="user-post-item"], [data-e2e="user-collection-item"], [data-e2e="user-favorite-item"]').forEach(tile=>{
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
// Runs inside the TikTok tab. Reads the open collection's name from its address and heading.
function detectCollectionName(){
  const m=location.pathname.match(/\/collection\/([^/?#]+)/);
  if(!m)return '';
  let slug='';
  try{slug=decodeURIComponent(m[1]);}catch{slug=m[1];}
  slug=slug.replace(/-\d{6,}$/,'');
  const plain=slug.replace(/-/g,' ').trim();
  const key=t=>t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,'');
  const heading=[...document.querySelectorAll('h1,h2,[data-e2e*="collection"]')].map(n=>n.textContent.trim()).find(t=>t&&t.length<=80&&key(t)===key(plain));
  return (heading||plain).slice(0,80);
}
// Runs inside the TikTok tab. Collects the TikTok post links shared in the open chat; message text is never read or returned.
async function captureChatInPage(){
  try{
    if(!location.pathname.startsWith('/messages'))throw new Error('Open a conversation in TikTok Messages (tiktok.com/messages) first.');
    const POST=/^\/@[^/]*\/(video|photo)\/(\d+)|^\/share\/(video|photo)\/(\d+)|^\/v\/(\d+)/;
    const SHORT=h=>h==='vm.tiktok.com'||h==='vt.tiktok.com';
    const TEXT=/https:\/\/(?:[\w-]+\.)?tiktok(?:v)?\.com\/[^\s<>"']+/gi;
    const found=new Map();
    const take=raw=>{
      try{
        const u=new URL(raw,location.href);
        if(u.protocol!=='https:'||u.port)return;
        const h=u.hostname,tiktok=h==='tiktok.com'||h==='tiktokv.com'||h.endsWith('.tiktok.com')||h.endsWith('.tiktokv.com');
        if(!tiktok)return;
        if(POST.test(u.pathname)||SHORT(h)||(/^(www\.)?tiktok\.com$/.test(h)&&u.pathname.startsWith('/t/')))found.set(u.origin+u.pathname,{url:u.origin+u.pathname,source:'chat'});
      }catch{}
    };
    const scan=()=>{
      document.querySelectorAll('a[href]').forEach(a=>take(a.href));
      // Shared posts may show only as link text. Only URLs are matched; nothing else from the text is kept.
      (document.body.innerText.match(TEXT)||[]).forEach(t=>take(t));
    };
    const wait=()=>new Promise(r=>setTimeout(r,1400));
    // The message pane: the scrollable ancestor of TikTok's message list; otherwise the scrollable element with the most post links.
    const LINKS='a[href*="/video/"],a[href*="/photo/"],a[href*="/share/"],a[href*="tiktok.com/t/"],a[href*="vm.tiktok.com"]';
    const scrollable=n=>n.scrollHeight>n.clientHeight+40&&/auto|scroll/.test(getComputedStyle(n).overflowY);
    let pane=null;
    for(let n=document.querySelector('[data-e2e="dm-new-message-list"]');n&&!pane;n=n.parentElement)if(scrollable(n))pane=n;
    if(!pane){
      const scrollers=[...document.querySelectorAll('*')].filter(scrollable);
      pane=scrollers.sort((a,b)=>b.querySelectorAll(LINKS).length-a.querySelectorAll(LINKS).length||(b.clientHeight*b.clientWidth)-(a.clientHeight*a.clientWidth))[0]||document.scrollingElement;
    }
    // How much has loaded, counting chat items too: a shared post that shows no link must not make us think loading has stopped.
    const loaded=()=>document.querySelectorAll('[data-e2e="dm-new-chat-item"]').length;
    scan();
    // TikTok loads older messages only when you scroll toward them. Sitting at the very top fires no new scroll event, so step up
    // in screen-sized moves (this also works when the list is laid out bottom-up) and keep going until nothing new arrives.
    let idle=0;
    for(let i=0;i<500&&idle<8;i++){
      const before=found.size,items=loaded(),height=pane.scrollHeight,top=pane.scrollTop;
      pane.dispatchEvent(new WheelEvent('wheel',{deltaY:-400,bubbles:true,cancelable:true}));
      pane.scrollBy(0,-Math.max(300,pane.clientHeight*.85));
      await wait();scan();
      const moved=pane.scrollTop!==top||pane.scrollHeight!==height;
      idle=(found.size===before&&loaded()===items&&!moved)?idle+1:(found.size===before&&loaded()===items?idle+0.5:0);
    }
    const cards=[...document.querySelectorAll('[data-e2e="dm-new-shared-video"]')];
    const stats={cards:cards.length,cardsWithLink:cards.filter(c=>c.querySelector(LINKS)).length,items:loaded()};
    return {posts:[...found.values()],stats};
  }catch(e){return {error:e.message||'Could not read this chat.'};}
}
let stopped=false;
const buttons=['check','continue','rescan','read-chat'];
const postId=p=>p.url.match(/\/(?:video|photo)\/(\d+)/)?.[1];
async function run(mode){
  el('status').textContent='Working…';
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
    let collection=el('collection').value.trim();
    if(!collection){
      collection=(await chrome.scripting.executeScript({target:{tabId:tab.id},func:detectCollectionName}))[0]?.result||'';
      if(collection)el('collection').value=collection;
    }
    const page=u.origin+u.pathname+u.search+u.hash;
    const inspection=(await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureInPage,args:['inspect',collection,page,null]}))[0]?.result;
    if(inspection?.error)throw new Error(inspection.error);
    if(!inspection)throw new Error('Chrome could not read this TikTok page. Refresh it and try again.');
    if(!inspection.posts?.length)throw new Error('No video links found on this page yet. Let the videos load and try again.');
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
    if(!confirm(`Found ${inspection.posts.length} loaded posts on this page. Import all of them? Keep this page open while importing.`))return;
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
    el('token').disabled=el('collection').disabled=false;el('stop').hidden=true;
  }
}
async function readChat(){
  el('status').textContent='Working…';
  buttons.forEach(id=>el(id).disabled=true);el('token').disabled=true;
  try{
    const token=el('token').value.trim();
    if(!token)throw new Error('Paste the pairing token from Unscroll Settings first.');
    await chrome.storage.local.set({unscrollToken:token});
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const u=new URL(tab.url||'');
    if(u.protocol!=='https:'||!(u.hostname==='www.tiktok.com'||u.hostname==='tiktok.com'))throw new Error('Open a conversation in TikTok Messages on www.tiktok.com first.');
    el('status').textContent='Reading the chat… scrolling up to load older messages.';
    const res=(await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureChatInPage}))[0]?.result;
    if(!res)throw new Error('Chrome could not read this page. Refresh it and try again.');
    if(res.error)throw new Error(res.error);
    if(!res.posts.length)throw new Error('No TikTok post links found in this chat. If posts show only as cards, tell me and I will adapt the reader.');
    if(!confirm(`Found ${res.posts.length} TikTok post link${res.posts.length===1?'':'s'} in this chat${res.stats?.cards>res.posts.length?` (the chat shows ${res.stats.cards} shared posts, ${res.stats.cards-res.stats.cardsWithLink} of them with no readable link)`:''}. Add the new ones to Unscroll? Only the links are saved, not the messages.`)){el('status').textContent='Cancelled. Nothing was added.';return;}
    const r=await fetch('http://127.0.0.1:8765/api/capture',{method:'POST',headers:{'Content-Type':'application/json','X-Unscroll-Token':token},body:JSON.stringify({posts:res.posts})});
    const data=await r.json();if(!r.ok)throw new Error(data.detail||'Import failed.');
    el('status').textContent=`${res.posts.length} links found${res.stats?.cards?` of ${res.stats.cards} shared posts`:''} · ${data.added} new · ${data.skipped} already in your library.${data.errors?.length?' Some links could not be used: '+data.errors.slice(0,2).join(' '):''} Open your library to process new posts.`;
  }catch(e){el('status').textContent=e.message==='Failed to fetch'?'Could not reach Unscroll. Start the local helper and try again.':e.message;}
  finally{buttons.forEach(id=>el(id).disabled=false);el('token').disabled=false;}
}
el('read-chat').addEventListener('click',readChat);
el('check').addEventListener('click',()=>run('check'));
el('continue').addEventListener('click',()=>run('continue'));
el('rescan').addEventListener('click',()=>run('rescan'));
el('stop').addEventListener('click',()=>{stopped=true;el('stop').disabled=true;el('status').textContent='Stopping after the current batch…';});
