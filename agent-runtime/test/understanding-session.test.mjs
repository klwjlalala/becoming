import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {PersonalUnderstanding} from '../understanding.mjs';
test('late confirmation matches next turn in source conversation only',async()=>{
 const store=new Store(':memory:'),other=store.createConversation('other').id;
 const u=new PersonalUnderstanding(store,{complete:async()=>JSON.stringify({evidence:[{ref:'e1',turn_index:0,quote:'我希望自由支配时间',kind:'direct_statement',event_time:null}],operations:[{operation:'CREATE',claim_ref:'c1',claim_id:null,expected_version:null,content:'用户重视自由',dimension:'values',basis:'ai_inference',scope:{},temporal_scope:'unknown',evidence:[{ref:'e1',relation:'support'}],reason:'用户表达偏好'}],confirmation:{claim_id:null,claim_ref:'c1',expected_version:1,turn_index:0,question:'你更重视自由吗？'}})});
 const t=store.append('我希望自由支配时间','你更重视自由吗？');const unrelated=store.append('是的','好的',[],other);
 await u.processTurn(t.id);assert.equal(u.list()[0].user_validation,'unconfirmed');assert.deepEqual(u.resolve(unrelated.id),[]);
 const next=store.append('是的','好的');assert.equal(u.resolve(next.id).length,1);assert.equal(u.list()[0].user_validation,'confirmed');store.close();
});
