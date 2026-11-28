import test from 'node:test';
import assert from 'node:assert/strict';
import {SYSTEM_PROMPT} from '../prompt.mjs';

test('system prompt preserves explicit task gates and ongoing artifact revision behavior',()=>{
  assert.match(SYSTEM_PROMPT,/【阶段性成果与持续修订】/);
  assert.match(SYSTEM_PROMPT,/不提前把最终成果包装成已完成/);
  assert.match(SYSTEM_PROMPT,/主动修订受影响部分/);
  assert.match(SYSTEM_PROMPT,/没有了.*立即完成已承诺的交付/s);
  assert.match(SYSTEM_PROMPT,/不要每收到一条新消息就自动重写全文/);
  assert.match(SYSTEM_PROMPT,/优先瞄准区间中部/);
  assert.match(SYSTEM_PROMPT,/中文写作要求.*非空白字符/);
  assert.match(SYSTEM_PROMPT,/不得用重复、空话或虚构内容凑字/);
  assert.match(SYSTEM_PROMPT,/区分“补充信息是否结束”与“批准执行某项操作”/);
  assert.match(SYSTEM_PROMPT,/确认问题应单独提出/);
  assert.match(SYSTEM_PROMPT,/只询问真正未解决的事项/);
  assert.match(SYSTEM_PROMPT,/没有了.*应视为该补充环节已完成/);
  assert.match(SYSTEM_PROMPT,/不要为了形式上的确认而重复提问/);
  assert.match(SYSTEM_PROMPT,/“没有了”不等于批准执行/);
  assert.match(SYSTEM_PROMPT,/只有全部约定的实质性问题与必要追问完成后，才发起最终补充确认/);
  assert.match(SYSTEM_PROMPT,/最终确认只问一次/);
  assert.match(SYSTEM_PROMPT,/不得与新的实质性问题合并/);
});
