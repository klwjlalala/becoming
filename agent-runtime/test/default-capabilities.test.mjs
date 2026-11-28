import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Store} from '../store.mjs';
import {AssetStore} from '../assets.mjs';
import {CapabilityRegistry} from '../capabilities/registry.mjs';
import {registerDefaultCapabilities} from '../capabilities/defaults.mjs';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/xj8AAAAASUVORK5CYII=','base64');

test('default image capability forwards cancellation and persists its local asset',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'becoming-default-image-'));
  const store=new Store(':memory:');
  try{
    const assetStore=new AssetStore(store,directory),controller=new AbortController();
    let received=null;
    const gateway={generateImage:async options=>{
      received=options;
      return {buffer:png,mime_type:'image/png',revised_prompt:'A quiet mountain landscape'};
    }};
    const registry=registerDefaultCapabilities({registry:new CapabilityRegistry(),gateway,assetStore,enableImage:true});
    const result=await registry.execute('image_generate',{prompt:'A quiet mountain landscape'},{signal:controller.signal});
    assert.equal(result.ok,true);
    assert.equal(received.prompt,'A quiet mountain landscape');
    assert.equal(received.size,'1024x1024');
    assert.equal(received.signal,controller.signal,'The user cancellation signal must reach the image provider');
    const block=result.result.blocks[0];
    assert.equal(block.type,'image');
    const stored=assetStore.read(block.asset_id);
    assert.equal(stored.asset.mime_type,'image/png');
    assert.deepEqual(stored.buffer,png);
  }finally{
    store.close();
    rmSync(directory,{recursive:true,force:true});
  }
});
