// Requires Playwright and Chromium; no production dependencies.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1280,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const url=process.env.GAME_URL||'http://127.0.0.1:8000';
 await page.goto(url);
 // Seed the original v1 structure to exercise migration without new fields.
 await page.evaluate(()=>localStorage.setItem('dragon-island-v1',JSON.stringify({coins:1500,food:8,xp:0,eggs:[2,1,1,0,0,0],nests:Array(8).fill(null),dragons:[{id:1,type:0,name:'小芽',fed:Date.now()-600000,born:Date.now()-600000}],discovered:[0],lastGift:Date.now(),daily:''})));
 await page.reload();assert.equal(await page.locator('.nest').count(),8);assert.equal(await page.locator('#coins').textContent(),'1,500');
 const saved=()=>page.evaluate(()=>JSON.parse(localStorage.getItem('dragon-island-v1')));
 assert.equal((await saved()).scene,'meadow');
 await page.locator('#cleanup').click();assert.equal((await saved()).coins,1505);await page.waitForTimeout(1200);assert.equal(await page.locator('#cleanup').count(),0);
 await page.locator('[data-friend="0"]').click();assert.match(await page.locator('#visitbadge').textContent(),/团子/);assert.equal(await page.locator('.nest').count(),8);
 await page.locator('[data-nest="0"]').click();assert.equal(await page.locator('#modal').evaluate(e=>e.open),false);
 await page.locator('#cleanup').click();assert.equal((await saved()).coins,1510);
 await page.locator('#home').click();await page.locator('[data-friend="0"]').click();assert.equal(await page.locator('#cleanup').count(),0);await page.locator('#home').click();
 await page.locator('#bag').click();await page.locator('[data-place="1"]').click();assert.equal((await saved()).eggs[1],0);assert.equal((await saved()).nests[0].type,1);
 // Move an existing incubation timer forward to verify hatching and discovery rewards.
 await page.evaluate(()=>{let s=JSON.parse(localStorage.getItem('dragon-island-v1'));s.nests[0].end=Date.now()-1;localStorage.setItem('dragon-island-v1',JSON.stringify(s));});await page.reload();
 await page.locator('[data-nest="0"]').click();assert.equal((await saved()).dragons.length,2);assert.equal((await saved()).xp,29);assert.deepEqual((await saved()).discovered,[0,1]);
 await page.locator('.dragonbtn').first().click();await page.locator('[data-feed]').click();assert.equal((await saved()).food,7);assert.equal((await saved()).xp,32);await page.locator('#close').click();
 await page.locator('#shop').click();await page.locator('[data-shop-page="1"]').click();assert.equal(await page.locator('[data-purchase="egg:4"]').isDisabled(),true);await page.locator('[data-shop-tab="supplies"]').click();await page.locator('[data-purchase="clock"]').click();assert.equal((await saved()).speedups,1);
 await page.locator('[data-shop-tab="scenes"]').click();await page.locator('[data-purchase="scene:violet"]').click();assert.ok((await saved()).ownedScenes.includes('violet'));await page.locator('#close').click();
 await page.locator('[data-scene="violet"]:is(button)').click();assert.equal(await page.locator('#world').getAttribute('data-scene'),'violet');
 await page.locator('#bag').click();await page.locator('[data-place="0"]').click();await page.locator('#bag').click();await page.locator('[data-speedup]').click();assert.equal((await saved()).speedups,0);await page.locator('#close').click();await page.locator('[data-nest="0"]').click();assert.equal((await saved()).dragons.length,3);assert.equal((await saved()).xp,42);
 await page.locator('#album').click();assert.equal(await page.locator('.album-card').count(),4);await page.locator('[data-album-page="1"]').click();assert.equal(await page.locator('.album-card').count(),2);await page.locator('[data-album-tab="nature"]').click();assert.equal(await page.locator('.album-card').count(),3);await page.locator('#close').click();
 await page.evaluate(()=>{const s=JSON.parse(localStorage.getItem('dragon-island-v1'));s.lastGift=Date.now()-120000;s.dragons[1].born=Date.now()-65000;s.dragons[2].born=Date.now();localStorage.setItem('dragon-island-v1',JSON.stringify(s));});
 await page.reload();const balance=(await saved()).coins;await page.locator('#collect').click();assert.equal((await saved()).coins,balance+15);await page.locator('#collect').click();assert.equal((await saved()).coins,balance+15);
 await page.reload();assert.equal(await page.locator('#world').getAttribute('data-scene'),'violet');assert.equal(await page.locator('.dragonbtn').count(),3);assert.equal(await page.locator('.nest').count(),8);
 await page.screenshot({path:'artifacts/home-v2.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:'artifacts/mobile-v2.png',fullPage:true});await page.locator('#shop').click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);console.log('PASS: v1 save migration; 8 nests; own/friend cleanup and daily limits; safe friend visits; egg placement; hatching/discovery XP; feeding; locked shop and paging; clock; scene purchase/switch/persistence; album categories/paging; mobile layout; no browser errors.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
