'use strict';
const IS_EXTENSION=location.protocol==='chrome-extension:';
const API_ROOT=IS_EXTENSION?'http://127.0.0.1:8765':'';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={token:'',session:{},data:{counts:{},tree:[],jobs:[]},posts:[],selected:new Set(),category:0,status:'',active:null,draft:[],tab:'overview',busy:false};
let toastTimer,searchTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500);}
async function api(path,body,method){
  const opts={headers:{'X-Unscroll-Token':state.token},method:method||(body===undefined?'GET':'POST')};
  if(body instanceof FormData)opts.body=body;
  else if(body!==undefined){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body);}
  let r;
  try{r=await fetch(API_ROOT+'/api/'+path,opts);}catch{throw new Error('The local helper is not running. Open Start.command, then retry the connection.');}
  if(!r.ok){let msg;try{const e=await r.json();msg=typeof e.detail==='string'?e.detail:JSON.stringify(e.detail);}catch{msg='Request failed. Is Unscroll still running?';}throw new Error(msg);}
  return r.json();
}
function show(id){const d=$(id);if(!d.open)d.showModal();}
async function action(fn){try{await fn();}catch(e){toast(e.message||'Something went wrong.');}}
function leaves(){return state.data.tree.flatMap(r=>r.children.map(s=>({...s,parent:r.name})));}
function label(id){const s=leaves().find(s=>s.id===id);return s?`${s.parent} / ${s.name}`:'Uncategorised';}
function currentName(){if(state.category){const p=state.data.tree.find(r=>r.id===state.category);return p?.name||leaves().find(s=>s.id===state.category)?.name||'All saves';}return ({ready:'Ready to read',unplaced:'Awaiting categories',suggested:'Worth keeping offline',failed:'Needs attention'})[state.status]||'All saves';}
function stat(name,value,note,icon){return `<article class="stat"><div class="stat-top">${name}<span class="stat-icon">${icon}</span></div><div class="stat-value">${Number(value||0).toLocaleString()}</div><div class="stat-note">${note}</div></article>`;}
function renderChrome(){
  const d=state.data,c=d.counts,n=currentName();
  $('#stats').innerHTML=stat('Saved posts',c.total,'Your whole collection','▣')+stat('Ideas unpacked',c.ready,'One entry for every post','✧')+stat('Categories',d.tree.length,'A little room for everything','⊞')+stat('Checked by you',c.reviewed,'Trust, one post at a time','✓');
  const nav=[['','All saves','▦',c.total],['ready','Ready to read','▤',c.ready],['suggested','Offline picks','↓',null],['failed','Needs attention','◌',c.failed||0]];
  $('#nav').innerHTML=nav.map(([s,t,i,count])=>`<button data-nav="${s}" class="${!state.category&&state.status===s?'active':''}"><span class="nav-icon">${i}</span>${t}${count!==null?`<span class="count">${count||0}</span>`:''}</button>`).join('');
  $('#category-nav').innerHTML=d.tree.length?d.tree.map(r=>`<button class="cat-parent ${state.category===r.id?'active':''}" data-cat="${r.id}"><span>⌑</span>${esc(r.name)}</button>${r.children.map(s=>`<button class="cat-child ${state.category===s.id?'active':''}" data-cat="${s.id}">${esc(s.name)}<span class="count">${s.count}</span></button>`).join('')}`).join(''):`<div class="empty-categories">Your ideas will find their places here.<br>Process a few saves to begin.</div>`;
  $('#breadcrumb-current').textContent=n;$('#results-title').textContent=n;
  $('#page-title').textContent=state.category?n:({ready:'A little wisdom, unpacked.',suggested:'Keep the good ones close.',failed:'A few saves need a hand.'})[state.status]||'Good ideas, kept close.';
  $('#queue-dot').textContent=d.job_counts?.queued||d.job_counts?.running?String((d.job_counts.queued||0)+(d.job_counts.running||0)):'';
  const old=$('#creator').value;
  $('#creator').innerHTML='<option value="">All creators</option>'+d.creators.map(x=>`<option value="${esc(x)}">@${esc(x)}</option>`).join('');$('#creator').value=old;
  const missing=Object.entries(state.session.tools||{}).filter(([,ok])=>!ok).map(([name])=>name);
  let banner='';
  if(!state.session.api_ready||missing.length)banner=`<div class="banner">Finish local setup to process posts: ${!state.session.api_ready?'Claude API key needed. ':''}${missing.length?esc(missing.join(', '))+' not installed. ':''} Run Setup.command from the Unscroll folder.<button class="text-btn" data-settings>View settings</button></div>`;
  else if(d.proposal&&!d.tree.length)banner='<div class="banner">Your category proposal is ready. Make it yours before anything is filed.<button class="text-btn" data-review-cats>Review categories →</button></div>';
  $('#setup-banner').innerHTML=banner;
  if($('#jobs-dialog').open)renderJobs();
}
function renderCards(){
  $('#result-count').textContent=state.posts.length;
  $('#cards').innerHTML=state.posts.length?state.posts.map(p=>{
    const e=p.entry,placement=p.placements.find(x=>x.is_primary),cat=placement?leaves().find(s=>s.id===placement.category_id):null;
    const color=cat?['','coral','purple','blue'][cat.id%4]:p.status==='failed'?'failed':'';
    const badge=cat?cat.name:p.status==='failed'?'Needs attention':e?'Awaiting categories':'Not processed';
    const activeJob=state.data.jobs.find(j=>j.post_id===p.id&&['running','queued'].includes(j.state));
    return `<article class="card ${state.selected.has(p.id)?'selected':''}"><div class="card-top"><span class="pill ${color}">${esc(badge)}</span><input type="checkbox" class="select-post" data-select="${esc(p.id)}" ${state.selected.has(p.id)?'checked':''} aria-label="Select ${esc(e?.title||p.caption||'post '+p.id)}"></div><h3><button class="open-entry" data-open="${esc(p.id)}">${esc(e?.title||p.caption?.slice(0,130)||'A saved idea, waiting to be unpacked.')}</button></h3>${e?`<ul class="card-points">${e.key_points.slice(0,3).map(k=>`<li>${esc(k.text)}</li>`).join('')}</ul>${e.thin?'<p class="card-blank">Limited source text. Read with care.</p>':''}`:`<p class="card-blank">${activeJob?esc(activeJob.kind+' · '+activeJob.state):'Open this post to process it or attach a local copy. Its own ideas will stay together.'}</p>`}${p.error?`<div class="error-text">${esc(p.error)}</div>`:''}${p.download_error?`<div class="error-text">Download: ${esc(p.download_error)}</div>`:''}${e?.download_suggestion?'<div class="suggestion">✧ Suggested for offline keeping</div>':''}<div class="card-bottom"><span class="avatar">${esc((p.creator||'s')[0].toUpperCase())}</span><span>${p.creator?'@'+esc(p.creator):'Saved on TikTok'}</span><span class="format">${p.download_path?'↓ Kept offline':p.reviewed?'✓ Checked':p.kind==='carousel'?'▧ Carousel':'▷ Video'}</span></div></article>`;
  }).join(''):`<div class="empty"><div class="empty-symbol">✳</div><h3>${state.data.counts.total?'Room to find something good.':'Your saves have a new home.'}</h3><p>${state.data.counts.total?'No posts match these filters. Try a broader idea or another category.':'Bring in your TikTok saves, and turn “I’ll come back to this” into something you actually do.'}</p><button class="button primary" data-import>${state.data.counts.total?'Import more saves':'Bring in your first saves'} →</button>${!state.data.counts.total?'<div class="empty-steps"><span><b>01</b> Import saves</span><span><b>02</b> Unpack ideas</span><span><b>03</b> Make them yours</span></div>':''}</div>`;
  updateSelection();
}
function updateSelection(){const n=state.selected.size;$('#selection-bar').hidden=!n;$('#selection-count').textContent=`${n} post${n===1?'':'s'} selected`;$('#process-selected').hidden=!n;}
async function loadPosts(){
  const params=new URLSearchParams({q:$('#search').value,category:state.category,status:state.status,creator:$('#creator').value,kind:$('#kind').value,after:$('#after').value,before:$('#before').value});
  const result=await api('posts?'+params);state.posts=result.posts;$('#search-warning').textContent=result.warning;renderCards();
}
async function refresh(){if(state.busy)return;state.busy=true;try{state.data=await api('state');renderChrome();await loadPosts();}finally{state.busy=false;}}
async function navigate(category,status){state.category=category;state.status=status;renderChrome();await loadPosts();}
function points(items){return items.map(k=>`<div class="evidence-point">${esc(k.text)}<details><summary>Check source quote</summary><blockquote>${esc(k.quote)}</blockquote></details></div>`).join('');}
async function openPost(id){state.active=await api('posts/'+id);state.tab='overview';renderDetail();show('#detail-dialog');}
function renderDetail(){
  const p=state.active,e=p.entry,primary=p.placements.find(x=>x.is_primary)?.category_id;
  const title=e?.title||p.caption||'Your saved post';
  $('#detail-content').innerHTML=`<span class="pill">${p.kind==='carousel'?'▧ Carousel':'▷ Video'}${p.reviewed?' · Checked by you':''}</span><h2>${esc(title)}</h2><div class="detail-meta"><span>${p.creator?'@'+esc(p.creator):'TikTok post'}</span><span>${esc(primary?label(primary):p.status)}</span>${p.saved_date?`<span>Saved ${esc(p.saved_date)}</span>`:''}</div><div class="detail-actions"><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer" class="button subtle">Original post ↗</a><button class="button subtle" data-select-detail>${state.selected.has(p.id)?'✓ Selected':'Select for download'}</button>${e?`<button class="button subtle" data-review>${p.reviewed?'Undo check':'Mark checked ✓'}</button>`:''}<button class="button subtle" data-process-one>${e?'Re-run AI':'Process post'} ✧</button></div>${p.error?`<div class="banner">${esc(p.error)}</div>`:''}${p.download_error?`<div class="banner">Download: ${esc(p.download_error)}</div>`:''}${p.download_path?`<div class="muted-note">Kept offline in ${esc(p.download_path)}</div>`:''}<div class="tabs"><button class="tab ${state.tab==='overview'?'active':''}" data-tab="overview">The ideas</button><button class="tab ${state.tab==='source'?'active':''}" data-tab="source">Full extracted source</button></div>${state.tab==='source'?renderSource(p):`${e?`<section class="detail-section"><h3>KEY POINTS</h3>${points(e.key_points)||'<p>No reliable key points could be extracted.</p>'}</section>${e.action_steps.length?`<section class="detail-section"><h3>PUT IT INTO PRACTICE</h3>${points(e.action_steps)}</section>`:''}${e.specifics.length?`<section class="detail-section"><h3>THE SPECIFICS, WORD FOR WORD</h3><div class="specifics">${e.specifics.map(s=>`<span>${esc(s)}</span>`).join('')}</div></section>`:''}${e.uncertainty||e.thin?`<div class="banner">${esc(e.uncertainty||'This source has limited reliable text.')}</div>`:''}<section class="detail-section"><h3>KEEP IT OFFLINE?</h3><p>${e.download_suggestion?'✧ Suggested':'Optional'} — ${esc(e.download_reason)}</p></section>`:'<p>This post has not been unpacked yet. Process it to extract the text and write its entry.</p>'}${renderPlacement(p)}${p.overlap.length?`<section class="detail-section"><h3>IDEAS THAT MIGHT OVERLAP</h3>${p.overlap.map(o=>`<button class="overlap-link" data-open="${esc(o.id)}">${esc(o.title)}<small>${esc(o.note)}</small></button>`).join('')}</section>`:''}<section class="detail-section"><h3>ATTACH LOCAL MEDIA</h3><p class="fineprint">If TikTok capture fails, attach ${p.kind==='carousel'?'the complete set of slide images in order':'a copy of this video'}. Attachments are temporary and removed after extraction. Use ordered filenames for carousels.</p><input id="local-files" type="file" ${p.kind==='carousel'?'multiple accept="image/png,image/jpeg,image/webp"':'accept="video/mp4,video/quicktime,video/webm,.mkv"'}><button class="button subtle" data-attach>Attach files</button></section>`}`;
}
function renderSource(p){if(!p.source)return '<p>No extraction yet. Process this post first.</p>';const s=p.source;return `<div class="banner">${s.warnings.map(esc).join(' ')}</div><div class="source-segment"><strong>CAPTION</strong><p>${esc(s.caption)||'No caption'}</p></div>${s.segments.map(x=>`<div class="source-segment"><strong>${esc(x.label)}</strong><p>${esc(x.text)||'No text detected'}</p></div>`).join('')}`;}
function renderPlacement(p){if(!leaves().length)return '';const primary=p.placements.find(x=>x.is_primary)?.category_id;return `<section class="detail-section"><h3>FILE THIS IDEA</h3><div class="placement-controls"><label for="primary-category">Primary subcategory</label><select id="primary-category"><option value="">Choose a place…</option>${leaves().map(s=>`<option value="${s.id}" ${s.id===primary?'selected':''}>${esc(s.parent+' / '+s.name)}</option>`).join('')}</select><details><summary class="text-btn">Additional subcategories</summary><div class="extras">${leaves().map(s=>`<label><input type="checkbox" value="${s.id}" name="extra" ${p.placements.some(x=>x.category_id===s.id&&!x.is_primary)?'checked':''}>${esc(s.name)}</label>`).join('')}</div></details><button class="button subtle" data-save-placement>Save placement</button></div></section>`;}
function openCategories(){
  if(state.data.tree.length){renderManage();}
  else{state.draft=structuredClone(state.data.proposal||[{name:'',subcategories:['']}]);renderDraft();}
  show('#category-dialog');
}
function renderDraft(){
  $('#category-description').textContent='Rename, combine or remove the proposed groups. Entries will be assigned only after you approve this two-level tree.';
  $('#category-editor').innerHTML=state.draft.map((r,i)=>`<div class="category-group"><div class="category-row"><input type="text" data-draft-parent="${i}" value="${esc(r.name)}" placeholder="Category name" aria-label="Category name" maxlength="80"><button class="remove" data-remove-parent="${i}" aria-label="Remove category">×</button></div>${r.subcategories.map((s,j)=>`<div class="category-row sub"><input type="text" data-draft-child="${i}:${j}" value="${esc(s)}" placeholder="Subcategory" aria-label="Subcategory name" maxlength="80"><button class="remove" data-remove-child="${i}:${j}" aria-label="Remove subcategory">×</button></div>`).join('')}<button class="text-btn" data-add-child="${i}">＋ Add subcategory</button>${state.draft.length>1?`<div class="manage-line"><select data-draft-merge-target="${i}" aria-label="Merge target"><option value="">Combine into…</option>${state.draft.map((t,k)=>k===i?'':`<option value="${k}">${esc(t.name||'Category '+(k+1))}</option>`).join('')}</select><button class="text-btn" data-draft-merge="${i}">Combine</button></div>`:''}</div>`).join('');
  $('#category-actions').innerHTML='<button class="button subtle" id="add-parent">＋ Add category</button><button class="button primary" id="approve-tree">Approve & organise →</button>';
}
function renderManage(){
  $('#category-description').textContent='Rename or merge categories while preserving your entries and their placements. Pause processing and wait for the current job before changing the tree.';
  const all=state.data.tree.flatMap(r=>[r,...r.children]);
  const row=r=>`<div class="manage-line"><input type="text" value="${esc(r.name)}" data-rename-value="${r.id}" aria-label="Rename ${esc(r.name)}" maxlength="80"><button class="text-btn" data-rename="${r.id}">Rename</button><select data-merge-target="${r.id}" aria-label="Merge target"><option value="">Merge into…</option>${all.filter(t=>t.id!==r.id&&(t.parent_id===null)===(r.parent_id===null)).map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select><button class="text-btn" data-merge="${r.id}">Merge</button></div>`;
  $('#category-editor').innerHTML=state.data.tree.map(r=>`<div class="category-group">${row(r)}${r.children.map(s=>row(s)).join('')}</div>`).join('');
  $('#category-actions').innerHTML='<button class="button subtle" data-unplaced>View entries awaiting placement</button>';
}
function renderJobs(){
  const d=state.data;$('#jobs-content').innerHTML=`<p class="muted-note">${d.paused?'Paused':'Running'} · ${d.job_counts?.queued||0} queued · ${d.job_counts?.running||0} active · ${d.job_counts?.done||0} completed · ${d.job_counts?.failed||0} failed</p>${d.jobs.length?d.jobs.map(j=>`<div class="job-row"><span class="pill ${j.state==='failed'?'failed':''}">${esc(j.state)}</span><div>${esc(({process:'Extract & write',place:'Place in categories',propose:'Propose category tree',download:'Keep offline',index:'Rebuild search'})[j.kind]||j.kind)}<small>${esc(j.caption?.slice(0,90)||j.post_id||'Whole library')}</small>${j.error?`<small class="job-error">${esc(j.error)}</small>`:''}</div>${j.state==='failed'?`<button class="text-btn" data-retry-job="${j.id}">Retry</button>`:''}</div>`).join(''):'<p>No active jobs. Import your saves, then start with a batch of 20.</p>'}`;
}
function renderSettings(){const s=state.session;$('#settings-content').innerHTML=`<div class="setting-row"><span>Speech recognition</span><small>English · local CPU · one worker</small></div><div class="setting-row"><span>Claude</span><small>${s.api_ready?'Configured':'API key needed'} · ${esc(s.model)}</small></div><div class="setting-row"><span>Media tools</span><small>${Object.entries(s.tools).map(([k,v])=>`${esc(k)} ${v?'✓':'missing'}`).join(' · ')}</small></div><div class="setting-row"><span>Permanent downloads</span><code>${esc(s.download_dir)}</code></div><div class="setting-row"><span>Claude token usage</span><small>${state.data.usage?.input_tokens||0} in · ${state.data.usage?.output_tokens||0} out</small></div><p class="muted-note">Extension pairing token — paste this into the Unscroll Chrome extension. Treat it like a local password.</p><div class="token-wrap">${esc(state.token)}</div><p class="muted-note">${esc(state.data.search_warning||'Search embeddings run locally. The first model download needs an internet connection.')}</p>`;}
document.addEventListener('click',event=>action(async()=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-nav'))return navigate(0,b.dataset.nav);
  if(b.dataset.cat)return navigate(Number(b.dataset.cat),'');
  if(b.dataset.open)return openPost(b.dataset.open);
  if(b.hasAttribute('data-import')||b.id==='open-import')return show('#import-dialog');
  if(b.hasAttribute('data-settings')||b.id==='settings'){renderSettings();return show('#settings-dialog');}
  if(b.hasAttribute('data-review-cats')||b.id==='manage-cats')return openCategories();
  if(b.id==='open-jobs'){renderJobs();return show('#jobs-dialog');}
  if(b.id==='do-import'){
    const text=$('#import-text').value;if(!text.trim())return toast('Choose an export file or paste some full post links.');
    const r=await api('import',{text});$('#import-result').textContent=`${r.added} added · ${r.enriched} updated · ${r.skipped} already saved${r.errors.length?' · '+r.errors.join(' '):''}`;await refresh();return;
  }
  if(b.id==='process-20'||b.id==='process-selected'||b.hasAttribute('data-process-one')||b.id==='process-all'){
    let r;
    if(b.hasAttribute('data-process-one')&&state.active.entry)r=await api(`posts/${state.active.id}/rerun`,{});
    else r=await api('process',b.hasAttribute('data-process-one')?{ids:[state.active.id]}:b.id==='process-selected'?{ids:[...state.selected]}:{limit:b.id==='process-all'?20000:20});
    toast(r.message||`${r.queued} posts queued. You can follow progress from Processing.`);return refresh();
  }
  if(b.id==='select-visible'){state.posts.forEach(p=>state.selected.add(p.id));renderCards();return;}
  if(b.id==='clear-selection'){state.selected.clear();renderCards();return;}
  if(b.id==='remove-unprocessed'||b.id==='remove-selected'){
    const includeProcessed=b.id==='remove-selected';
    const preview=await api('imports/remove-preview',includeProcessed?{ids:[...state.selected],include_processed:true}:{all_unprocessed:true});
    if(!preview.count)return toast(includeProcessed?'No selected posts remain in your library.':'No eligible unprocessed posts. Completed entries and permanent downloads are protected.');
    const description=includeProcessed?'Their completed entries and category placements will also be removed from the library. Downloaded files stay on disk.':'This covers your whole library, regardless of filters. Completed entries and permanent downloads are protected.';
    if(!confirm(`Remove ${preview.count} ${includeProcessed?'selected':'unprocessed'} posts from Unscroll and cancel their queued jobs? ${description} Your TikTok saves stay intact. You can undo removal in Settings.`))return;
    const r=await api('imports/remove',{ids:preview.ids,...(includeProcessed?{include_processed:true}:{})});
    preview.ids.forEach(id=>state.selected.delete(id));
    if(state.active&&preview.ids.includes(state.active.id)){$('#detail-dialog').close();state.active=null;}
    toast(r.message);return refresh();
  }
  if(b.id==='undo-removal'){toast((await api('imports/undo',{})).message);return refresh();}
  if(b.id==='download-selected'){const r=await api('download',{ids:[...state.selected]});toast(`${r.queued} selected downloads queued.`);return refresh();}
  if(b.id==='pause'||b.id==='resume'){toast((await api(b.id,{})).message);return refresh();}
  if(b.id==='suggest-cats'){
    if(state.data.tree.length||state.data.proposal)return openCategories();
    if(!state.data.counts.ready)return toast('Process a few posts first so categories reflect your actual ideas.');
    toast((await api('categories/propose',{})).message);await refresh();renderJobs();return show('#jobs-dialog');
  }
  if(b.dataset.tab){state.tab=b.dataset.tab;return renderDetail();}
  if(b.hasAttribute('data-select-detail')){const id=state.active.id;state.selected.has(id)?state.selected.delete(id):state.selected.add(id);renderCards();return renderDetail();}
  if(b.hasAttribute('data-review')){await api(`posts/${state.active.id}/review`,{});state.active=await api('posts/'+state.active.id);renderDetail();return refresh();}
  if(b.hasAttribute('data-save-placement')){const primary=Number($('#primary-category').value);if(!primary)return toast('Choose a primary subcategory.');const extras=$$('input[name=extra]:checked').map(x=>Number(x.value));toast((await api(`posts/${state.active.id}/move`,{primary_id:primary,extra_ids:extras})).message);state.active=await api('posts/'+state.active.id);renderDetail();return refresh();}
  if(b.hasAttribute('data-attach')){const files=[...$('#local-files').files];if(!files.length)return toast('Choose a media file first.');const f=new FormData();files.forEach(x=>f.append('files',x));toast((await api(`posts/${state.active.id}/media`,f)).message);state.active=await api('posts/'+state.active.id);renderDetail();return refresh();}
  if(b.dataset.retryJob){toast((await api('jobs/'+b.dataset.retryJob+'/retry',{})).message);return refresh();}
  if(b.id==='clear-dates'){$('#after').value='';$('#before').value='';return loadPosts();}
  if(b.id==='add-parent'){state.draft.push({name:'',subcategories:['']});return renderDraft();}
  if(b.hasAttribute('data-add-child')){state.draft[Number(b.dataset.addChild)].subcategories.push('');return renderDraft();}
  if(b.hasAttribute('data-remove-parent')){state.draft.splice(Number(b.dataset.removeParent),1);return renderDraft();}
  if(b.dataset.removeChild){const [i,j]=b.dataset.removeChild.split(':').map(Number);state.draft[i].subcategories.splice(j,1);return renderDraft();}
  if(b.hasAttribute('data-draft-merge')){const i=Number(b.dataset.draftMerge),val=$(`[data-draft-merge-target="${i}"]`).value;if(val==='')return toast('Choose a category to combine into.');const target=state.draft[Number(val)];target.subcategories=[...new Set([...target.subcategories,...state.draft[i].subcategories])];state.draft.splice(i,1);return renderDraft();}
  if(b.id==='approve-tree'){toast((await api('categories/approve',{categories:state.draft})).message);$('#category-dialog').close();return refresh();}
  if(b.dataset.rename){toast((await api(`categories/${b.dataset.rename}/rename`,{name:$(`[data-rename-value="${b.dataset.rename}"]`).value})).message);await refresh();return renderManage();}
  if(b.dataset.merge){const id=Number($(`[data-merge-target="${b.dataset.merge}"]`).value);if(!id)return toast('Choose a merge target.');toast((await api(`categories/${b.dataset.merge}/merge`,{target_id:id})).message);await refresh();return renderManage();}
  if(b.hasAttribute('data-unplaced')){$('#category-dialog').close();return navigate(0,'unplaced');}
  if(b.id==='rebuild'){toast((await api('search/rebuild',{})).message);return refresh();}
  if(b.id==='export'){const r=await fetch(API_ROOT+'/api/export',{headers:{'X-Unscroll-Token':state.token}});if(!r.ok)throw new Error('Export failed.');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='unscroll-library.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
}));
document.addEventListener('change',event=>action(async()=>{
  const el=event.target;
  if(el.dataset.select){el.checked?state.selected.add(el.dataset.select):state.selected.delete(el.dataset.select);renderCards();}
  if(['creator','kind','after','before'].includes(el.id))await loadPosts();
  if(el.id==='export-file'&&el.files[0]){$('#import-text').value=await el.files[0].text();$('#import-result').textContent=el.files[0].name+' loaded. Click Import to continue.';}
}));
document.addEventListener('input',event=>{
  const el=event.target;
  if(el.id==='search'){clearTimeout(searchTimer);searchTimer=setTimeout(()=>action(loadPosts),400);}
  if(el.hasAttribute('data-draft-parent'))state.draft[Number(el.dataset.draftParent)].name=el.value;
  if(el.dataset.draftChild){const [i,j]=el.dataset.draftChild.split(':').map(Number);state.draft[i].subcategories[j]=el.value;}
});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){event.preventDefault();$('#search').focus();}});
let poll;
async function boot(){
  clearInterval(poll);
  if(IS_EXTENSION){
    const saved=await chrome.storage.local.get(['unscrollToken','siftToken']);
    state.token=saved.unscrollToken||saved.siftToken||'';
    if(!state.token){show('#connect-dialog');return;}
  }
  try{
    state.session=await api('session');state.token=state.session.token;
    if(IS_EXTENSION)await chrome.storage.local.set({unscrollToken:state.token});
    await refresh();
    if($('#connect-dialog').open)$('#connect-dialog').close();
    poll=setInterval(async()=>{
      if(document.hidden)return;
      try{await refresh();}catch(e){clearInterval(poll);$('#connection-error').textContent=e.message;show('#connect-dialog');}
    },5000);
  }catch(e){$('#connection-error').textContent=e.message;show('#connect-dialog');}
}
$('#connect-helper').addEventListener('click',()=>action(async()=>{
  const token=$('#pairing-token').value.trim();
  if(IS_EXTENSION&&token){await chrome.storage.local.set({unscrollToken:token});}
  await boot();
}));
$('#connection-settings').addEventListener('click',()=>{
  if(IS_EXTENSION)chrome.tabs.create({url:'http://127.0.0.1:8765'});
  else window.open('http://127.0.0.1:8765','_blank','noopener');
});
action(boot);
