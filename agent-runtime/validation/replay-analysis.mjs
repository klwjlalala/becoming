const sectionPatterns=[
  ['你在这里',/你在这里/],
  ['你早就拥有的意义',/你早就拥有的意义|早已拥有的意义/],
  ['被你忽略的部分',/被你忽略的部分|你可能忽略的部分/],
  ['你的人生罗盘',/你的人生罗盘|人生罗盘/],
  ['设计更多意义时刻',/设计更多意义时刻|亲手设计更多|更多有意义的时刻/],
  ['带着问题生活',/带着问题生活/],
  ['陪你一起变好的人',/陪你一起变好的人|一起变好的人/],
  ['你的人生季节',/你的人生季节/]
];

const isConversationClosure=value=>/^(?:没有了|没有其他(?:补充|想说的)?了?|就这些|没了|到这里|先这样|暂时没有其他补充)[。！!？?]*$/u.test(String(value||'').trim());

export function analyzeReplay(turns){
  const handbookTurns=turns.filter(turn=>/(?:^|\n)#\s*(?:《)?个人意义设计手册(?:》)?/.test(turn.assistant||''));
  const firstHandbookTurn=handbookTurns[0]||null;
  const handbookTurn=handbookTurns.at(-1)||null;
  const handbook=handbookTurn?.assistant||'';
  const compact=Array.from(handbook.replace(/\s/g,'')).length;
  const missingSections=sectionPatterns.filter(([,pattern])=>!pattern.test(handbook)).map(([name])=>name);
  const tableLines=handbook.split('\n').filter(line=>/^\s*\|.*\|\s*$/.test(line));
  const ending=handbook.trim().slice(-500);
  const latestSubstantiveUserTurn=turns.filter(turn=>turn.kind==='replayed_user_turn'&&!isConversationClosure(turn.user)).at(-1)||null;
  const finalTurn=turns.at(-1)||null;
  const finalResponse=finalTurn?.assistant||'';
  const artifactAfterLatestInput=!!handbookTurn&&(!latestSubstantiveUserTurn||handbookTurn.index>=latestSubstantiveUserTurn.index);
  const finalConfirmationResponse=latestSubstantiveUserTurn?.assistant||'';
  const finalConfirmationQuestionMarks=(finalConfirmationResponse.match(/[？?]/g)||[]).length;
  const knownAgeTurn=turns.find(turn=>turn.kind==='replayed_user_turn'&&/\d{1,3}\s*岁/u.test(String(turn.user||'')))||null;
  const knownAge=!!knownAgeTurn;
  const ageQuestionPattern=/(?:\d{1,3}\s*岁[^。！？\n]{0,20}(?:对吗|可以吗|是吗|吗[？?])|(?:年龄|岁数)[^。！？\n]{0,12}(?:对吗|可以吗|确认))/u;
  const reasksKnownAgeTurns=knownAge?turns.filter(turn=>turn.index>knownAgeTurn.index&&ageQuestionPattern.test(String(turn.assistant||''))).map(turn=>turn.index):[];
  const reasksKnownAge=reasksKnownAgeTurns.length>0;
  const finalConfirmationQuestionPattern=/(?:你还有.{0,12}(?:补充|修正)|还有.{0,12}(?:补充|修正)|(?:补充|修正).{0,12}(?:吗[？?]|有没有|是否))/u;
  const finalConfirmationTurns=turns.filter(turn=>turn.kind==='replayed_user_turn'&&finalConfirmationQuestionPattern.test(String(turn.assistant||'')));
  const prematureFinalConfirmationTurns=finalConfirmationTurns.filter(turn=>turn.index!==latestSubstantiveUserTurn?.index).map(turn=>turn.index);
  const finalConfirmationQuestionIntents=finalConfirmationResponse.match(/有没有|是否|谁|什么样|什么时候|哪个|哪位|为什么|怎么(?:样|做)?|你想不想|你希望|你想|能不能|可不可以|还有什么|还有没有|是否还有/gu)||[];
  const asksStandaloneFinalConfirmation=finalConfirmationQuestionPattern.test(finalConfirmationResponse)&&finalConfirmationQuestionMarks===1&&finalConfirmationQuestionIntents.length===1&&!reasksKnownAge&&!/个人意义设计手册/.test(finalConfirmationResponse);

  const checks={
    personal_meaning_handbook_generated:{passed:!!handbookTurn,detail:{turn_index:handbookTurn?.index??null}},
    handbook_length_5000_to_7000_characters:{passed:compact>=5000&&compact<=7000,detail:{characters_without_whitespace:compact}},
    handbook_covers_all_eight_named_sections:{passed:missingSections.length===0,detail:{missing_sections:missingSections}},
    handbook_has_reflective_closing:{passed:ending.length>=100&&/意义|时刻|生活|未来|山|风|树|开始|继续/.test(ending),detail:{ending_excerpt:ending.slice(-180)}},
    handbook_uses_markdown_tables:{passed:tableLines.length>=4,detail:{table_lines:tableLines.length}},
    handbook_generated_after_last_substantive_user_turn:{passed:artifactAfterLatestInput,detail:{handbook_turn_index:handbookTurn?.index??null,latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,final_turn_index:finalTurn?.index??null}},
    handbook_generated_after_closure_signal:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||handbookTurn?.index===finalTurn.index,detail:{first_handbook_turn_index:firstHandbookTurn?.index??null,latest_handbook_turn_index:handbookTurn?.index??null,final_turn_index:finalTurn?.index??null,final_turn_is_closure:isConversationClosure(finalTurn?.user)}},
    handbook_not_prematurely_delivered:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||!firstHandbookTurn||firstHandbookTurn.index===finalTurn.index||/(?:草稿|初稿|阶段性版本)/.test((firstHandbookTurn.assistant||'').slice(0,180)),detail:{first_handbook_turn_index:firstHandbookTurn?.index??null,final_turn_index:finalTurn?.index??null,final_turn_is_closure:isConversationClosure(finalTurn?.user),first_handbook_is_explicitly_draft:!!firstHandbookTurn&&/(?:草稿|初稿|阶段性版本)/.test((firstHandbookTurn.assistant||'').slice(0,180))}},
    known_age_was_not_reconfirmed:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||!reasksKnownAge,detail:{known_age_from_user:knownAge,reasks_known_age:reasksKnownAge,reasks_known_age_turn_indices:reasksKnownAgeTurns}},
    final_confirmation_not_asked_before_last_substantive_turn:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||prematureFinalConfirmationTurns.length===0,detail:{latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,final_confirmation_turn_indices:finalConfirmationTurns.map(turn=>turn.index),premature_confirmation_turn_indices:prematureFinalConfirmationTurns}},
    standalone_final_confirmation_was_requested:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||asksStandaloneFinalConfirmation,detail:{latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,confirmation_question_marks:finalConfirmationQuestionMarks,question_intent_count:finalConfirmationQuestionIntents.length,contains_addition_question:finalConfirmationQuestionPattern.test(finalConfirmationResponse),known_age_from_user:knownAge,reasks_known_age:reasksKnownAge,response_excerpt:finalConfirmationResponse.slice(0,240)}},
    final_confirmation_was_requested_once_after_last_substantive_turn:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||(finalConfirmationTurns.length===1&&finalConfirmationTurns[0].index===latestSubstantiveUserTurn?.index),detail:{latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,final_confirmation_turn_indices:finalConfirmationTurns.map(turn=>turn.index)}}
  };
  return {
    handbook_turn_index:handbookTurn?.index??null,
    first_handbook_turn_index:firstHandbookTurn?.index??null,
    handbook_turn_indices:handbookTurns.map(turn=>turn.index),
    handbook_characters:Array.from(handbook).length,
    handbook_characters_without_whitespace:compact,
    handbook_section_titles:(handbook.match(/^#{1,3}\s+.+$/gm)||[]),
    handbook_table_lines:tableLines.length,
    handbook_missing_sections:missingSections,
    handbook_ending_excerpt:ending.slice(-180),
    latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,
    final_turn_index:finalTurn?.index??null,
    final_turn_response_characters:Array.from(finalResponse).length,
    final_turn_is_closure:isConversationClosure(finalTurn?.user),
    final_confirmation_response:finalConfirmationResponse,
    final_confirmation_question_marks:finalConfirmationQuestionMarks,
    known_age_from_user:knownAge,
    reasks_known_age:reasksKnownAge,
    reasks_known_age_turn_indices:reasksKnownAgeTurns,
    final_confirmation_turn_indices:finalConfirmationTurns.map(turn=>turn.index),
    premature_final_confirmation_turn_indices:prematureFinalConfirmationTurns,
    checks
  };
}
