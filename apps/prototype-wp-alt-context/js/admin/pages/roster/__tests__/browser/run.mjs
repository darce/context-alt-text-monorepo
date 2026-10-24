import { chromium, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const artifacts = path.resolve('../../roster-evidence/browser');
await fs.mkdir(artifacts,{recursive:true});
let browser;
try {
 browser = await chromium.launch({headless:true,executablePath:'/home/gate/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome',args:['--no-sandbox']});
} catch (error) {
 await fs.writeFile(path.join(artifacts,'results.json'),JSON.stringify({status:'BLOCKED_ENVIRONMENT',rendered_viewports:0,planned_viewports:[{width:1440,height:1000},{width:719,height:960}],error:String(error),stack:error.stack},null,2));
 throw error;
}
const base='http://127.0.0.1:4184/js/admin/pages/roster/__tests__/browser/index.html';
const fixtureImage = '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="#dce4e8"/><circle cx="90" cy="66" r="32" fill="#8d9da6"/><path d="M32 166a58 58 0 0 1 116 0" fill="#8d9da6"/></svg>';
const entries=Array.from({length:10},(_,index)=>({
  id:index+41,person_uuid:`person-${index+41}`,name:index===0?'Example Person':index===1?'Example Person with a deliberately long neutral directory name to verify reflow':'Example Person '+(index+1),
  tags:index===1?['a-very-long-neutral-tag-to-check-word-wrapping-within-the-directory-cell']:[],
  cluster_count:3,clusters:[{cluster_id:`group-${index+41}`,identity_count:1,
    representative_identity:{identity_id:`face-${index+41}`,media_id:index+101,media_url:'/fixture/image.svg',bbox:null,similarity:null},instances:[]}],
  queue_memberships:[],updated_at:'2026-10-24T00:00:00Z',source_version:1,projection_status:'current',projection_refreshed_at:'2026-10-24T00:00:00Z',
}));
const results=[];
try {
for (const viewport of [{width:1440,height:1000},{width:719,height:960}]) {
 const context=await browser.newContext({viewport});const page=await context.newPage();const requests=[];const errors=[];
 let mode='populated';
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const request=route.request();const u=new URL(request.url());
  if(u.origin!=='http://127.0.0.1:4184')return route.abort();
  if(!u.pathname.startsWith('/fixture/'))return route.continue();
  requests.push({method:request.method(),url:u.pathname+u.search});
  if(request.method()!=='GET')throw new Error('Unexpected mutation in navigation proof: '+request.method());
  if(u.pathname==='/fixture/image.svg')return route.fulfill({contentType:'image/svg+xml',body:fixtureImage});
  if(u.pathname==='/fixture/entries')return route.fulfill({json:mode==='zero'?[]:entries});
  if(u.pathname.match(/\/persons\/\d+\/media$/)){
   if(mode==='loading')await new Promise(resolve=>setTimeout(resolve,900));
   if(mode==='error')return route.fulfill({status:500,json:{code:'fixture_error',message:'Fixture photo transport unavailable'}});
   const offset=Number(u.searchParams.get('offset')||0);
   return route.fulfill({json:{media:mode==='empty'?[]:Array.from({length:offset?1:10},(_,i)=>({identity_id:`photo-${offset+i}`,media_id:201+offset+i,media_url:'/fixture/image.svg',bbox:null,similarity:null,cluster_id:'group-41'})),limit:50,offset,total:mode==='empty'?0:51,truncated:mode==='empty'?false:offset===0}});
  }
  return route.fulfill({json:{}});
 });
 await page.goto(base+'#/roster?s=Example');
 await expect(page.getByRole('link',{name:'View photos for Example Person',exact:true})).toBeVisible();
 await expect(page.locator('.acx-roster-entries__table tbody tr')).toHaveCount(10);
 const evidence=page.getByRole('button',{name:'Example Person',exact:true}).locator('img');
 await expect(evidence).toHaveAttribute('width','64');
 const directoryBox=await evidence.boundingBox();expect(directoryBox.width).toBe(64);expect(directoryBox.height).toBe(64);
 const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));expect(overflow.scroll).toBeLessThanOrEqual(overflow.width);
 await page.screenshot({path:path.join(artifacts,`directory-${viewport.width}.png`),fullPage:true});
 // Keyboard follows native collection link and retains stable identity.
 const link=page.getByRole('link',{name:'View photos for Example Person',exact:true});await link.focus();
 const focusStyle=await link.evaluate(el=>({style:getComputedStyle(el).outlineStyle,width:getComputedStyle(el).outlineWidth}));expect(focusStyle.style).not.toBe('none');
 await page.keyboard.press('Enter');
 await expect(page).toHaveURL(/person=person-41/);await expect(page).toHaveURL(/section=photos/);
 const photos=page.getByRole('region',{name:'Photos',exact:true});await expect(photos).toBeFocused();
 await expect(photos.getByText('1–10 of 51 photos',{exact:true})).toBeVisible();
 const photoBox=await photos.boundingBox();expect(photoBox.y).toBeGreaterThanOrEqual(0);expect(photoBox.y).toBeLessThan(viewport.height);
 await page.screenshot({path:path.join(artifacts,`photos-focused-${viewport.width}.png`),fullPage:false});
 await expect(page.getByRole('heading',{name:'Example Person',exact:true,level:3})).toBeAttached();
 const header=page.locator('.acx-roster__person-workspace-header');const headerImage=header.locator('img');
 await header.scrollIntoViewIfNeeded();await expect(headerImage).toHaveAttribute('width','96');const headerBox=await headerImage.boundingBox();expect(headerBox.width).toBe(96);expect(headerBox.height).toBe(96);
 await page.screenshot({path:path.join(artifacts,`header-${viewport.width}.png`)});
 await headerImage.dispatchEvent('error');const fallback=header.locator('[data-face-missing]');await expect(fallback).toBeVisible();expect((await fallback.boundingBox()).width).toBe(96);
 await header.getByRole('link',{name:'View photos',exact:true}).focus();await page.keyboard.press('Enter');await expect(photos).toBeFocused();
 const next=photos.getByRole('button',{name:'Next photos'});await next.focus();await expect(next).toBeInViewport();await page.keyboard.press('Enter');await expect(photos.getByText('51–51 of 51 photos',{exact:true})).toBeVisible();
 await page.reload();await expect(photos).toBeFocused();await expect(photos.getByText('1–10 of 51 photos',{exact:true})).toBeVisible();
 mode='error';await page.reload();await expect(photos.getByRole('alert')).toContainText(/Could not load this person's photos|Fixture photo transport unavailable/);await expect(photos).toBeFocused();await page.screenshot({path:path.join(artifacts,`error-${viewport.width}.png`)});
 mode='empty';await page.reload();await expect(photos.getByText('No photos of this person yet.',{exact:true})).toBeVisible();
 mode='loading';await page.reload();await expect(photos.getByRole('status')).toHaveText('Loading photos…');await expect(photos.getByText('1–10 of 51 photos',{exact:true})).toBeVisible();
 mode='zero';await page.goto(base+'#/roster?s=');await page.reload();await expect(page.getByText('No people yet',{exact:true})).toBeVisible();
 expect(errors).toEqual([]);expect(requests.some(r=>r.url.includes('/persons/41/media?limit=50&offset=50'))).toBeTruthy();
 results.push({viewport,status:'PASS',directoryBox,headerBox,photoBox,overflow,focusStyle,requests,pageErrors:errors,limits:'Actual RosterPage + providers + main.scss; offline neutral fixtures only. Pagination reload uses existing offset reset behavior. No live site, identity mutations or cross-lane composition claim.'});
 await context.close();
}
await fs.writeFile(path.join(artifacts,'results.json'),JSON.stringify({status:'PASS',results},null,2));
console.log('PASS: 2 viewports; actual production RosterPage and current main.scss; keyboard, geometry, navigation, pagination, reload, loading/error/empty/fallback.');
} catch(error) {
 await fs.writeFile(path.join(artifacts,'results.json'),JSON.stringify({status:'FAIL',results,error:String(error),stack:error.stack},null,2));throw error;
} finally {await browser.close();}
