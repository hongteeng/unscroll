// Real Chromium DOM tests with synthetic TikTok pages; no account/network access.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../extension/popup.js'),'utf8');
const tile=id=>`<div data-e2e="user-post-item" style="height:50px"><a href="https://www.tiktok.com/@test/video/${id}">Video ${id}</a></div>`;
const controls=['token','open-library','choose-collection','check','continue','rescan','stop','collection','status'].map(id=>`<input id="${id}">`).join('');
const fixture=`${controls}<h1>My 20 saved videos</h1>
<div id="scroll-box" style="height:300px;overflow-y:auto"><div id="collection-grid" data-e2e="user-post-item-list">${Array.from({length:20},(_,i)=>tile(100+i)).join('')}
<div hidden>${tile(999)}</div><div data-e2e="user-favorite-item-list">${tile(777)}</div></div></div>
<section><h2>Likes and recommendations</h2><div data-e2e="user-post-item-list">${tile(800)}${tile(801)}</div></section>
<script id="SIGI_STATE" type="application/json">{"items":[{"id":"100","desc":"Selected caption"},{"id":"800","desc":"Not selected"}]}</script>`;
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.UNSCROLL_CHROMIUM||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage();
    await page.route('https://www.tiktok.com/**',route=>route.fulfill({contentType:'text/html',body:fixture}));
    await page.goto('https://www.tiktok.com/@test/favorites');
    await page.evaluate(()=>{window.chrome={storage:{local:{get:async()=>({})}}};});
    await page.evaluate(source);
    const inspect=async()=>{
      const result=await page.evaluate(()=>captureInPage('inspect','Test',location.href,null));
      if(result.error)throw new Error(result.error);
      return result;
    };
    await assert.rejects(inspect,/Choose the collection/);
    await page.evaluate(()=>chooseCollectionInPage());
    await page.locator('#collection-grid a').first().click();
    await page.locator('h1').evaluate(e=>e.textContent='Switched before opening popup');
    await assert.rejects(inspect,/collection changed/);
    await page.locator('h1').evaluate(e=>e.textContent='My 20 saved videos');
    let batch=await inspect();
    assert.equal(batch.posts.length,20);
    assert.deepEqual(batch.posts.map(p=>p.url.match(/\d+$/)[0]),Array.from({length:20},(_,i)=>String(100+i)));
    assert.equal(batch.posts[0].caption,'Selected caption');
    assert(batch.posts.every(p=>p.collections[0]==='Test'));
    await page.locator('#collection-grid').evaluate(e=>e.style.display='contents');
    await page.locator('#collection-grid > [data-e2e="user-post-item"]').evaluateAll(nodes=>nodes.forEach(e=>e.style.display='contents'));
    assert.equal((await inspect()).posts.length,20);
    await page.locator('#collection-grid').evaluate(e=>e.style.display='block');
    await page.locator('#collection-grid > [data-e2e="user-post-item"]').evaluateAll(nodes=>nodes.forEach(e=>e.style.display='block'));
    const originalScope=batch.scope;
    await page.evaluate(()=>captureInPage('down','Test',location.href,null));
    assert((await page.locator('#scroll-box').evaluate(e=>e.scrollTop))>0);
    assert.equal(await page.evaluate(()=>window.scrollY),0);
    await page.locator('h1').evaluate(e=>e.textContent='Another collection');
    await assert.rejects(inspect,/collection changed/);
    await page.locator('h1').evaluate(e=>e.textContent='My 20 saved videos');
    await page.locator('#collection-grid').evaluate(e=>e.hidden=true);
    await assert.rejects(inspect,/collection changed/);
    await page.locator('#collection-grid').evaluate(e=>e.hidden=false);
    await page.locator('#collection-grid').evaluate(e=>e.replaceWith(e.cloneNode(true)));
    await assert.rejects(inspect,/Choose the collection/);
    await page.evaluate(()=>chooseCollectionInPage());
    await page.locator('section [data-e2e="user-post-item"] a').first().click();
    batch=await inspect();
    assert.notEqual(batch.scope,originalScope);
    assert.equal(batch.posts.length,2);
    await page.evaluate(()=>history.pushState({},'',location.href+'?collection=changed'));
    await assert.rejects(inspect,/Choose the collection/);
    console.log('Collection scope checks passed: 20 selected videos only, hidden/other grids excluded, metadata scoped by ID, correct scroll container, collection switch and detached grid blocked.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
