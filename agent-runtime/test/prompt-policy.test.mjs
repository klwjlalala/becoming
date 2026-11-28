import test from 'node:test';
import assert from 'node:assert/strict';
import {SYSTEM_PROMPT} from '../prompt.mjs';

test('system prompt preserves explicit task gates and ongoing artifact revision behavior',()=>{
  assert.match(SYSTEM_PROMPT,/【阶段性成果与持续修订】/);
  assert.match(SYSTEM_PROMPT,/不提前把最终成果包装成已完成/);
  assert.match(SYSTEM_PROMPT,/主动修订受影响部分/);
  assert.match(SYSTEM_PROMPT,/没有了.*未完成的成果/s);
  assert.match(SYSTEM_PROMPT,/不要每收到一条新消息就自动重写全文/);
});
