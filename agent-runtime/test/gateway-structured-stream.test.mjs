import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {Gateway} from '../agent.mjs';

function frame(payload){return 'data: '+JSON.stringify(payload)+'\n\n';}

test('Gateway aggregates fragmented native tool calls from SSE streams',async()=>{
  const server=createServer((req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    res.write(frame({choices:[{delta:{tool_calls:[{index:0,id:'call_1',type:'function',function:{name:'make_chart',arguments:'{"title":'}}]}}]}));
    res.write(frame({choices:[{delta:{tool_calls:[{index:0,function:{arguments:'"Reading"}'}}]}}]}));
    res.write(frame({choices:[{delta:{},finish_reason:'tool_calls'}]}));
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const gateway=new Gateway('http://127.0.0.1:'+server.address().port);
  try{
    const response=await gateway.streamStructured([{role:'user',content:'Create a chart'}],{tools:[]});
    assert.equal(response.tool_calls.length,1);
    assert.equal(response.tool_calls[0].function.name,'make_chart');
    assert.deepEqual(JSON.parse(response.tool_calls[0].function.arguments),{title:'Reading'});
    assert.equal(response.finish_reason,'tool_calls');
  }finally{await new Promise(resolve=>server.close(resolve));}
});

test('Gateway streams text deltas and reports a completed structured response',async()=>{
  const server=createServer((req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    res.write(frame({choices:[{delta:{content:'Hello '},finish_reason:null}]}));
    res.write(frame({choices:[{delta:{content:'world.'},finish_reason:'stop'}]}));
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const gateway=new Gateway('http://127.0.0.1:'+server.address().port),tokens=[];
  try{
    const response=await gateway.streamStructured([{role:'user',content:'Say hello'}],{tools:[],onToken:token=>tokens.push(token)});
    assert.equal(response.text,'Hello world.');
    assert.equal(response.tool_calls.length,0);
    assert.equal(tokens.join(''),'Hello world.');
    assert.equal(response.streamed,true);
  }finally{await new Promise(resolve=>server.close(resolve));}
});
