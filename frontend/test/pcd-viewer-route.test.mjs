import assert from 'node:assert/strict';
import test from 'node:test';
import config from '../vite.config.js';

test('production source-viewer link resolves its real HTML in root-based Vite development', () => {
  let middleware;
  config.plugins[0].configureServer({middlewares:{use(handler){middleware=handler;}}});
  const request = {url:'/vue/pcd-viewer.html?project=site&projection=example'};
  let next = false;
  middleware(request,{},() => {next=true;});
  assert.equal(request.url,'/pcd-viewer.html?project=site&projection=example');
  assert.equal(next,true);
  const untouched={url:'/vue/another-page.html'};
  middleware(untouched,{},() => {});
  assert.equal(untouched.url,'/vue/another-page.html');
});
