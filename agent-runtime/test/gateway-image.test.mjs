import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {Gateway} from '../agent.mjs';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/xj8AAAAASUVORK5CYII=','base64');

test('Gateway forwards generated images and validates the returned bytes',async()=>{
  const server=createServer(async(req,res)=>{
    if(req.url!=='/v1/llm/images'){res.writeHead(404);res.end();return;}
    let body='';for await(const chunk of req)body+=chunk;
    const input=JSON.parse(body);
    assert.equal(input.prompt,'A quiet mountain landscape');
    res.writeHead(200,{'Content-Type':'application/json'});
    res.end(JSON.stringify({image_base64:png.toString('base64'),mime_type:'image/png',revised_prompt:'A quiet mountain landscape at dawn'}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const gateway=new Gateway('http://127.0.0.1:'+server.address().port);
  try{
    const image=await gateway.generateImage({prompt:'A quiet mountain landscape'});
    assert.equal(image.mime_type,'image/png');
    assert.deepEqual(image.buffer,png);
    assert.equal(image.revised_prompt,'A quiet mountain landscape at dawn');
  }finally{await new Promise(resolve=>server.close(resolve));}
});

test('Gateway rejects malformed image provider responses',async()=>{
  const server=createServer((req,res)=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({image_base64:'not-base64',mime_type:'image/svg+xml'}));});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const gateway=new Gateway('http://127.0.0.1:'+server.address().port);
  try{await assert.rejects(gateway.generateImage({prompt:'Generate a small image'}),/Invalid generated image response/);}
  finally{await new Promise(resolve=>server.close(resolve));}
});
