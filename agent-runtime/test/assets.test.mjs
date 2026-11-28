import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Store} from '../store.mjs';
import {AssetStore} from '../assets.mjs';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/xj8AAAAASUVORK5CYII=','base64');

test('AssetStore persists and validates local image assets',()=>{
  const dir=mkdtempSync(join(tmpdir(),'becoming-assets-')),store=new Store(':memory:');
  try{
    const assets=new AssetStore(store,dir),saved=assets.save(png,'image/png');
    assert.match(saved.id,/^[0-9a-f-]{36}$/i);
    const loaded=assets.read(saved.id);
    assert.equal(loaded.asset.mime_type,'image/png');
    assert.deepEqual(loaded.buffer,png);
    assert.equal(assets.get('../escape'),null);
    assert.equal(assets.read('00000000-0000-0000-0000-000000000000'),null);
    assert.throws(()=>assets.save(Buffer.from('not an image'),'image/png'));
    assert.throws(()=>assets.save(png,'image/svg+xml'));
  }finally{store.close();rmSync(dir,{recursive:true,force:true});}
});
