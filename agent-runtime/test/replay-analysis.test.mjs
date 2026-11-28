import test from 'node:test';
import assert from 'node:assert/strict';
import {analyzeReplay} from '../validation/replay-analysis.mjs';

const handbook=[
  '# 《个人意义设计手册》',
  '## 你在这里',
  '## 你早就拥有的意义',
  '## 被你忽略的部分',
  '## 你的人生罗盘',
  '## 设计更多意义时刻',
  '## 带着问题生活',
  '## 陪你一起变好的人',
  '## 你的人生季节',
  '| 维度 | 观察 |',
  '|---|---|',
  '| 兴趣 | 创造 |',
  '| 价值 | 自由 |',
  '意义会在生活中继续展开。'
].join('\n')+'意义会在生活中继续展开。'.repeat(500);

test('replay analysis checks the latest handbook rather than the final conversational acknowledgement',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'第一轮回答',assistant:'继续提问'},
    {index:2,kind:'replayed_user_turn',user:'自由和帮助他人',assistant:handbook},
    {index:3,kind:'replayed_user_turn',user:'补充：帮助别人走出迷茫',assistant:'我可以整合进手册'},
    {index:4,kind:'replayed_user_turn',user:'暂时没有，但我确实渴望',assistant:'我理解了'},
    {index:5,kind:'replayed_user_turn',user:'没有了',assistant:'好，先到这里。'}
  ];
  const result=analyzeReplay(turns);
  assert.equal(result.handbook_turn_index,2);
  assert.ok(result.handbook_characters_without_whitespace>=5000);
  assert.equal(result.handbook_table_lines,4);
  assert.equal(result.handbook_missing_sections.length,0);
  assert.equal(result.final_turn_response_characters,7);
  assert.equal(result.final_turn_is_closure,true);
  assert.equal(result.latest_substantive_user_turn_index,4);
  assert.equal(result.checks.personal_meaning_handbook_generated.passed,true);
  assert.equal(result.checks.handbook_covers_all_eight_named_sections.passed,true);
  assert.equal(result.checks.handbook_generated_after_last_substantive_user_turn.passed,false);
  assert.equal(result.checks.handbook_generated_after_closure_signal.passed,false);
  assert.equal(result.checks.handbook_not_prematurely_delivered.passed,false);
  assert.equal(result.first_handbook_turn_index,2);
});

test('replay analysis passes when the handbook follows the final substantive user input',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'我的生活目标',assistant:'继续提问'},
    {index:2,kind:'replayed_user_turn',user:'没有了',assistant:handbook}
  ];
  const result=analyzeReplay(turns);
  assert.equal(result.checks.handbook_generated_after_last_substantive_user_turn.passed,true);
  assert.equal(result.checks.handbook_generated_after_closure_signal.passed,true);
  assert.equal(result.checks.handbook_not_prematurely_delivered.passed,true);
  assert.equal(result.final_turn_is_closure,true);
});
