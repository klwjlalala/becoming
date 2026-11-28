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
  const knownAge=turns.some(turn=>turn.kind==='replayed_user_turn'&&/\\d{1,3}\\s*岁/u.test(String(turn.user||'')));
  const reasksKnownAge=knownAge&&/(?:年龄|(?:你|自己)(?:现在|前面)?(?:是)?\\s*\\d{1,3}\\s*岁|按\\s*\\d{1,3}\\s*岁)/u.test(finalConfirmationResponse);
  const asksStandaloneFinalConfirmation=/(?:补充|修正)/.test(finalConfirmationResponse)&&finalConfirmationQuestionMarks===1&&!reasksKnownAge&&!/个人意义设计手册/.test(finalConfirmationResponse);

  const checks={
    personal_meaning_handbook_generated:{passed:!!handbookTurn,detail:{turn_index:handbookTurn?.index??null}},
    handbook_length_5000_to_7000_characters:{passed:compact>=5000&&compact<=7000,detail:{characters_without_whitespace:compact}},
    handbook_covers_all_eight_named_sections:{passed:missingSections.length===0,detail:{missing_sections:missingSections}},
    handbook_has_reflective_closing:{passed:ending.length>=100&&/意义|时刻|生活|未来|山|风|树|开始|继续/.test(ending),detail:{ending_excerpt:ending.slice(-180)}},
    handbook_uses_markdown_tables:{passed:tableLines.length>=4,detail:{table_lines:tableLines.length}},
    handbook_generated_after_last_substantive_user_turn:{passed:artifactAfterLatestInput,detail:{handbook_turn_index:handbookTurn?.index??null,latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,final_turn_index:finalTurn?.index??null}},
    handbook_generated_after_closure_signal:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||handbookTurn?.index===finalTurn.index,detail:{first_handbook_turn_index:firstHandbookTurn?.index??null,latest_handbook_turn_index:handbookTurn?.index??null,final_turn_index:finalTurn?.index??null,final_turn_is_closure:isConversationClosure(finalTurn?.user)}},
    handbook_not_prematurely_delivered:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||!firstHandbookTurn||firstHandbookTurn.index===finalTurn.index||/(?:草稿|初稿|阶段性版本)/.test((firstHandbookTurn.assistant||'').slice(0,180)),detail:{first_handbook_turn_index:firstHandbookTurn?.index??null,final_turn_index:finalTurn?.index??null,final_turn_is_closure:isConversationClosure(finalTurn?.user),first_handbook_is_explicitly_draft:!!firstHandbookTurn&&/(?:草稿|初稿|阶段性版本)/.test((firstHandbookTurn.assistant||'').slice(0,180))}},
    known_age_was_not_reconfirmed:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||!knownAge||!reasksKnownAge,detail:{known_age_from_user:knownAge,reasks_known_age:reasksKnownAge,response_excerpt:finalConfirmationResponse.slice(0,240)}},
    standalone_final_confirmation_was_requested:{passed:!finalTurn||!isConversationClosure(finalTurn.user)||asksStandaloneFinalConfirmation,detail:{latest_substantive_user_turn_index:latestSubstantiveUserTurn?.index??null,confirmation_question_marks:finalConfirmationQuestionMarks,contains_addition_question:/补充|修正/.test(finalConfirmationResponse),known_age_from_user:knownAge,reasks_known_age:reasksKnownAge,response_excerpt:finalConfirmationResponse.slice(0,240)}}
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
    checks
  };
}
