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
async function captureInPage(scroll,collection){
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
  if(scroll){
    let unchanged=0;
    for(let i=0;i<25;i++){
      const before=posts.size;
      window.scrollBy(0,Math.max(500,window.innerHeight*.85));
      await new Promise(r=>setTimeout(r,1600));scan();
      unchanged=before===posts.size?unchanged+1:0;
      if(unchanged>=6)break;
    }
  }
  return [...posts.values()];
}
async function run(scroll){
  el('capture').disabled=el('refresh').disabled=true;
  try{
    const token=el('token').value.trim();
    if(!token)throw new Error('Paste the pairing token from Unscroll Settings first.');
    await chrome.storage.local.set({unscrollToken:token});
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const u=new URL(tab.url||'');
    if(u.protocol!=='https:'||!(u.hostname==='www.tiktok.com'||u.hostname==='tiktok.com'))throw new Error('Open your Favorites or a post on www.tiktok.com first.');
    el('status').textContent=scroll?'Scrolling and collecting loaded links…':'Reading loaded posts…';
    const [result]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:captureInPage,args:[scroll,el('collection').value.trim()]});
    const posts=result.result||[];
    if(!posts.length)throw new Error('No full post links found. Open Favorites and let the grid load.');
    const r=await fetch('http://127.0.0.1:8765/api/capture',{method:'POST',headers:{'Content-Type':'application/json','X-Unscroll-Token':token},body:JSON.stringify({posts})});
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||'Capture failed.');
    el('status').textContent=`${posts.length} loaded links found. ${data.added} new · ${data.enriched} updated · ${data.skipped} already saved. ${data.errors.length?data.errors.join(' '):'Process new posts in Unscroll. This scan does not prove the full collection was loaded.'}`;
  }catch(e){el('status').textContent=e.message==='Failed to fetch'?'Could not reach Unscroll. Start the local app and try again.':e.message;}
  finally{el('capture').disabled=el('refresh').disabled=false;}
}
el('capture').addEventListener('click',()=>run(false));
el('refresh').addEventListener('click',()=>run(true));
