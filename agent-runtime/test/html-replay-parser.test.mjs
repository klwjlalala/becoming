import test from 'node:test';
import assert from 'node:assert/strict';
import {parseSource} from '../validation/html-replay-parser.mjs';

test('HTML replay parser extracts the prompt and only original user turns',()=>{
  const html='<pre class="prompt-text">Role: &quot;Life designer&quot;\nFollow the stages.</pre>'+
    '<section id="dialogue">'+
    '<article class="message user"><details class="prompt-details"><pre>the prompt</pre></details></article>'+
    '<article class="message assistant"><div class="plain">An assistant question.</div></article>'+
    '<article class="message user"><div class="bubble"><div class="plain">我想研究 &amp; 探索<br>AI。</div></div></article>'+
    '<article class="message user"><div class="bubble"><div class="plain">没有了。</div></div></article>'+
    '</section>';
  const result=parseSource(html);
  assert.equal(result.prompt,'Role: "Life designer"\nFollow the stages.');
  assert.deepEqual(result.userTurns,['我想研究 & 探索\nAI。','没有了。']);
});

test('HTML replay parser rejects documents without the prompt block',()=>{
  assert.throws(()=>parseSource('<section id="dialogue"></section>'),/prompt-text/);
});
