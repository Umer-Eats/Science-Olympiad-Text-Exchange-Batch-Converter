import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8766');
await expect(page.locator('#engine-status')).not.toHaveText('Starting…');
await expect(page.locator('#nav-count')).not.toHaveText('0',{timeout:30000});
await page.screenshot({path:'output/batch-converter-desktop.png',fullPage:true});
for(const route of ['queue','upload','guide']){
  await page.goto('http://127.0.0.1:8766/#'+route);
  await expect(page.locator('#'+route)).toBeVisible();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,route+' desktop overflow');
}
await page.goto('http://127.0.0.1:8766/#queue');
await page.locator('#status-filter').selectOption('needs_review');
await page.locator('.job-row').first().click();
await expect(page.locator('#save-review')).toBeVisible();
await page.screenshot({path:'output/batch-converter-review.png',fullPage:true});
await page.locator('#reviewer-name').fill('UI verification');
await page.locator('#save-review').click();
await expect(page.locator('#toast')).toContainText('Review saved');
await page.reload();await expect(page.locator('#reviewer-name')).toHaveValue('UI verification');
await page.locator('#reviewer-name').fill('');await page.locator('#save-review').click();await expect(page.locator('#toast')).toContainText('Review saved');
await page.locator('#approve-review').click();await expect(page.locator('#toast')).toContainText('reviewer');
await page.setViewportSize({width:390,height:844});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'review mobile overflow');
for(const route of ['overview','queue','upload','guide']){
  await page.goto('http://127.0.0.1:8766/#'+route);
  await expect(page.locator('#'+route)).toBeVisible();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,route+' mobile overflow');
}
await page.goto('http://127.0.0.1:8766/#overview');await page.screenshot({path:'output/batch-converter-mobile.png',fullPage:true});
assert.deepEqual(errors,[]);await browser.close();console.log('Dashboard, review persistence, approval guard and 390px layouts passed.');
