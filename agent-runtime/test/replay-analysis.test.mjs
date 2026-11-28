import test from 'node:test';
import assert from 'node:assert/strict';
import {analyzeReplay} from '../validation/replay-analysis.mjs';

const handbook=[
  '# 个人意义设计手册',
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
  assert.equal(result.checks.standalone_final_confirmation_was_requested.passed,false);
  assert.equal(result.checks.known_age_was_not_reconfirmed.passed,true);
  assert.equal(result.first_handbook_turn_index,2);
});

test('a no-more-additions reply completes the final check without repeating known facts',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'我今年28岁。',assistant:'明白，我会按28岁来理解。'},
    {index:2,kind:'replayed_user_turn',user:'我的生活目标',assistant:'我会按你说的28岁来写。还有什么想补充或修正的吗？'},
    {index:3,kind:'replayed_user_turn',user:'没有了',assistant:handbook}
  ];
  const result=analyzeReplay(turns);
  assert.equal(result.known_age_from_user,true);
  assert.equal(result.reasks_known_age,false);
  assert.equal(result.checks.known_age_was_not_reconfirmed.passed,true);
  assert.equal(result.checks.handbook_generated_after_last_substantive_user_turn.passed,true);
  assert.equal(result.checks.handbook_generated_after_closure_signal.passed,true);
  assert.equal(result.checks.handbook_not_prematurely_delivered.passed,true);
  assert.equal(result.checks.standalone_final_confirmation_was_requested.passed,true);
  assert.equal(result.checks.final_confirmation_not_asked_before_last_substantive_turn.passed,true);
  assert.equal(result.checks.final_confirmation_was_requested_once_after_last_substantive_turn.passed,true);
  assert.equal(result.final_turn_is_closure,true);
});

test('replay analysis rejects combining a known-age reconfirmation with the final additions check',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'我今年28岁。',assistant:'明白。'},
    {index:2,kind:'replayed_user_turn',user:'我的生活目标',assistant:'你现在是28岁，对吗？还有没有什么想补充的？'},
    {index:3,kind:'replayed_user_turn',user:'没有了',assistant:handbook}
  ];
  const result=analyzeReplay(turns);
  assert.equal(result.known_age_from_user,true);
  assert.equal(result.reasks_known_age,true);
  assert.equal(result.checks.known_age_was_not_reconfirmed.passed,false);
  assert.equal(result.checks.standalone_final_confirmation_was_requested.passed,false);
});


test('replay analysis rejects a premature final check that is repeated after the last substantive answer',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'我今年28岁。',assistant:'明白，我会按28岁来理解。'},
    {index:2,kind:'replayed_user_turn',user:'我希望自由支配人生，也想帮助别人。',assistant:'你身边有没有能聊这些的人？另外还有什么想补充或修正的吗？'},
    {index:3,kind:'replayed_user_turn',user:'暂时没有，但我确实渴望这样的关系。',assistant:'写手册前最后确认一下：还有什么想补充或修正的吗？'},
    {index:4,kind:'replayed_user_turn',user:'没有了',assistant:handbook}
  ];
  const result=analyzeReplay(turns);
  assert.deepEqual(result.final_confirmation_turn_indices,[2,3]);
  assert.deepEqual(result.premature_final_confirmation_turn_indices,[2]);
  assert.equal(result.checks.final_confirmation_not_asked_before_last_substantive_turn.passed,false);
  assert.equal(result.checks.final_confirmation_was_requested_once_after_last_substantive_turn.passed,false);
  assert.equal(result.checks.standalone_final_confirmation_was_requested.passed,true);
});

test('replay analysis rejects combining the final additions check with a substantive question',()=>{
  const turns=[
    {index:0,kind:'initial_instruction',assistant:'开始探索'},
    {index:1,kind:'replayed_user_turn',user:'我今年28岁。',assistant:'明白。'},
    {index:2,kind:'replayed_user_turn',user:'我希望拥有能深入交流的关系。',assistant:'你身边有没有适合聊这些的人？另外，你还有什么想补充或修正的吗？'},
    {index:3,kind:'replayed_user_turn',user:'没有了',assistant:handbook}
  ];
  const result=analyzeReplay(turns);
  assert.deepEqual(result.final_confirmation_turn_indices,[2]);
  assert.equal(result.checks.final_confirmation_not_asked_before_last_substantive_turn.passed,true);
  assert.equal(result.checks.standalone_final_confirmation_was_requested.passed,false);
  assert.equal(result.checks.final_confirmation_was_requested_once_after_last_substantive_turn.passed,true);
});