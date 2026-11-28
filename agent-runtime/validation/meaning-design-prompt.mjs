import assert from 'node:assert/strict';
import {readFileSync, mkdirSync, writeFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {Agent, Gateway} from '../agent.mjs';
import {Store} from '../store.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/meaning-design-dialogue.json', import.meta.url), 'utf8'));
const prompt = readFileSync(new URL('./fixtures/meaning-design-prompt.txt', import.meta.url), 'utf8').trim();
const maxCalls = Number(process.env.MEANING_DESIGN_MAX_CALLS || 16);
const output = resolve(process.env.MEANING_DESIGN_REPORT || 'agent-runtime/artifacts/meaning-design-prompt.json');

class BudgetedGateway extends Gateway {
  constructor(url, limit) {
    super(url);
    this.limit = limit;
    this.calls = 0;
    this.trace = [];
    this.timings = [];
  }
  async *stream(messages, options = {}) {
    if (this.calls >= this.limit) throw new Error('Meaning-design evaluation model-call budget exhausted');
    const call = ++this.calls;
    const started = performance.now();
    let answer = '';
    try {
      for await (const chunk of super.stream(messages, options)) {
        answer += chunk;
        yield chunk;
      }
      this.trace.push({
        call,
        input_characters: messages.reduce((n, m) => n + (m.content || '').length, 0),
        history_turns: messages.filter(m => m.role === 'user' || m.role === 'assistant').length - 1,
        user_input: messages.at(-1)?.content || '',
        output: answer
      });
    } catch (error) {
      this.trace.push({call, error: error.message, user_input: messages.at(-1)?.content || ''});
      throw error;
    } finally {
      this.timings.push(Math.round(performance.now() - started));
    }
  }
}

const model = new BudgetedGateway(process.env.BECOMING_GATEWAY || 'http://127.0.0.1:8000', maxCalls);
const store = new Store(':memory:');
const agent = new Agent(store, model, {historyTurns: 12});
const report = {
  fixture: fixture.fixture,
  fictional_data_only: fixture.fictional_data_only === true,
  prompt_characters: Array.from(prompt).length,
  planned_user_answers: fixture.answers.length,
  history_window: 12,
  memory_enabled: false,
  understanding_enabled: false,
  growth_tools_enabled: false,
  turns: [],
  checks: {},
  model_calls: 0
};

function check(name, passed, detail = null) {
  report.checks[name] = {passed: !!passed, ...(detail === null ? {} : {detail})};
}

try {
  assert.equal(fixture.fictional_data_only, true, 'Evaluation fixture must contain fictional data only');
  assert.ok(prompt.length > 2000, 'Original prompt fixture is unexpectedly short');
  assert.equal(fixture.answers.length, 12, 'Expected the complete 12-answer dialogue fixture');

  const inputs = [prompt, ...fixture.answers];
  let promptRetainedBeforeFinal = false;

  for (let i = 0; i < inputs.length; i++) {
    if (i === inputs.length - 1) {
      promptRetainedBeforeFinal = store.history(12, 'default').some(turn => turn.user === prompt);
    }
    const turn = await agent.reply(inputs[i], 'default');
    report.turns.push({
      index: i + 1,
      user_input: inputs[i],
      assistant: turn.assistant,
      turn_id: turn.id
    });
    mkdirSync(dirname(output), {recursive: true});
    report.model_calls = model.calls;
    report.trace = model.trace;
    report.call_durations_ms = model.timings;
    writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  }

  const first = report.turns[0].assistant;
  const final = report.turns.at(-1).assistant;
  const finalLength = Array.from(final.replace(/\s/g, '')).length;
  const sectionPatterns = [
    ['你在这里', /你在这里/],
    ['你早就拥有的意义', /你早就拥有的意义|早已拥有的意义/],
    ['被你忽略的部分', /被你忽略的部分|你可能忽略的部分/],
    ['你的人生罗盘', /你的人生罗盘|人生罗盘/],
    ['设计更多意义时刻', /设计更多意义时刻|亲手设计更多/],
    ['带着问题生活', /带着问题生活/],
    ['陪你一起变好的人', /陪你一起变好的人|一起变好的人/],
    ['你的人生季节', /你的人生季节|人生季节/],
    ['结尾', /写给未来的你|结语|最后想对你说/]
  ];
  const missingSections = sectionPatterns.filter(([, pattern]) => !pattern.test(final)).map(([name]) => name);
  const markdownTableLines = final.split('\n').filter(line => /^\s*\|.*\|\s*$/.test(line));
  const hasImageSyntax = /!\[[^\]]*\]\([^)]+\)|<img\b/i.test(report.turns.map(t => t.assistant).join('\n'));

  check('first_turn_has_progress_1_of_4', /进度\s*1\s*\/\s*4|进度1\/4/.test(first));
  check('first_turn_starts_with_warm_introduction', /人生意义设计课|人生设计课程/.test(first));
  check('first_turn_asks_about_current_life', /最近|过去七天|过去一周/.test(first) && /年龄|岁|人生季节/.test(first));
  check('initial_prompt_retained_at_final_turn', promptRetainedBeforeFinal, {history_window: 12, total_prior_turns: store.history(12).length});
  check('final_response_is_personal_meaning_handbook', /个人意义设计手册/.test(final));
  check('final_response_length_5000_to_7000_characters', finalLength >= 5000 && finalLength <= 7000, {characters_without_whitespace: finalLength});
  check('final_response_covers_all_nine_sections', missingSections.length === 0, {missing_sections: missingSections});
  check('final_response_uses_markdown_tables', markdownTableLines.length >= 4, {table_lines: markdownTableLines.length});
  check('conversation_contains_image_markup', hasImageSyntax, {note: 'Markup is only a diagnostic; it does not prove an image-generation tool was invoked.'});

  report.final_characters_without_whitespace = finalLength;
  report.final_table_lines = markdownTableLines.length;
  report.missing_sections = missingSections;
  report.prompt_retained_before_final = promptRetainedBeforeFinal;
  report.final_response = final;
  report.model_calls = model.calls;
  report.trace = model.trace;
  report.call_durations_ms = model.timings;
  report.status = Object.values(report.checks).every(item => item.passed) ? 'passed' : 'needs_review';
  mkdirSync(dirname(output), {recursive: true});
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n');

  console.log(JSON.stringify({
    status: report.status,
    model_calls: model.calls,
    user_answers: fixture.answers.length,
    history_window: 12,
    prompt_retained_before_final: promptRetainedBeforeFinal,
    final_characters_without_whitespace: finalLength,
    final_table_lines: markdownTableLines.length,
    checks: report.checks,
    report: output
  }, null, 2));

  if (report.status !== 'passed') process.exitCode = 1;
} catch (error) {
  report.status = 'failed';
  report.error = error.message;
  report.model_calls = model.calls;
  report.trace = model.trace;
  report.call_durations_ms = model.timings;
  mkdirSync(dirname(output), {recursive: true});
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.error(JSON.stringify({status: 'failed', error: error.message, model_calls: model.calls, report: output}));
  process.exitCode = 1;
} finally {
  store.close();
}
