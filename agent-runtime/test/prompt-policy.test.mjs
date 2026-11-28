import test from 'node:test';
import assert from 'node:assert/strict';
import {SYSTEM_PROMPT} from '../prompt.mjs';

test('system prompt preserves explicit task gates and ongoing artifact revision behavior',()=>{
  assert.match(SYSTEM_PROMPT,/【阶段性成果与持续修订】/);
  assert.match(SYSTEM_PROMPT,/不提前把最终成果包装成已完成/);
  assert.match(SYSTEM_PROMPT,/主动修订受影响部分/);
  assert.match(SYSTEM_PROMPT,/没有了.*未完成的成果/s);
  assert.match(SYSTEM_PROMPT,/不要每收到一条新消息就自动重写全文/);
  assert.match(SYSTEM_PROMPT,/优先瞄准区间中部/);
  assert.match(SYSTEM_PROMPT,/中文写作要求.*非空白字符/);
  assert.match(SYSTEM_PROMPT,/不得用重复、空话或虚构内容凑字/);
  assert.match(SYSTEM_PROMPT,/确认视为硬门槛/);
  assert.match(SYSTEM_PROMPT,/单独询问最终确认/);
  assert.match(SYSTEM_PROMPT,/不要与其他实质问题合并/);
  assert.match(SYSTEM_PROMPT,/没有了.*应视为该补充环节已完成/);
  assert.match(SYSTEM_PROMPT,/不要为了形式上的确认而重复提问/);
  assert.match(SYSTEM_PROMPT,/“没有了”不等于批准执行/);
});
