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

test('message visual blocks and image assets survive a SQLite process restart',()=>{
  const dir=mkdtempSync(join(tmpdir(),'becoming-restart-'));
  const dbPath=join(dir,'agent.sqlite3'),assetDir=join(dir,'assets');
  let store=new Store(dbPath);
  try{
    const assets=new AssetStore(store,assetDir),saved=assets.save(png,'image/png');
    const blocks=[{type:'image',asset_id:saved.id,alt:'山顶远望城市',caption:'辅助理解场景'}];
    const turn=store.append('请画出这个场景','已经生成图片。',[],'default',null,null,blocks);
    store.close();
    store=new Store(dbPath);
    const reopenedAssets=new AssetStore(store,assetDir);
    const restored=store.turn(turn.id);
    assert.deepEqual(restored.content_blocks,blocks,'Structured visual blocks must survive reopening SQLite');
    const restoredAsset=reopenedAssets.read(saved.id);
    assert.ok(restoredAsset,'Asset metadata and file must remain available after restart');
    assert.equal(restoredAsset.asset.mime_type,'image/png');
    assert.deepEqual(restoredAsset.buffer,png,'Image bytes must survive restart unchanged');
  }finally{
    try{store.close();}catch{}
    rmSync(dir,{recursive:true,force:true});
  }
});
