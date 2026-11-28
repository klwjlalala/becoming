import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
export class Store {
  constructor(path){
    this.db=new DatabaseSync(path);
    this.db.exec(`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL);
      INSERT OR IGNORE INTO conversations VALUES('default','长期会话',CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,user TEXT NOT NULL,assistant TEXT NOT NULL,created_at TEXT NOT NULL,conversation_id TEXT NOT NULL DEFAULT 'default' REFERENCES conversations(id) ON DELETE CASCADE);
      CREATE TABLE IF NOT EXISTS conversation_instructions(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,content TEXT NOT NULL CHECK(length(trim(content))>0 AND length(content)<=16000),source_turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS conversation_instruction_sources(conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,source_turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,created_at TEXT NOT NULL,PRIMARY KEY(conversation_id,source_turn_id));
      CREATE TABLE IF NOT EXISTS turn_requests(request_id TEXT PRIMARY KEY,turn_id TEXT NOT NULL UNIQUE REFERENCES turns(id) ON DELETE CASCADE);
      CREATE TABLE IF NOT EXISTS background_jobs(id INTEGER PRIMARY KEY,turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,error TEXT,priority INTEGER NOT NULL DEFAULT 0, UNIQUE(turn_id,kind));
      CREATE TABLE IF NOT EXISTS long_memories(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT NOT NULL,category TEXT NOT NULL CHECK(category IN ('fact','experience','subjective')),quote TEXT NOT NULL,source_turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
      CREATE UNIQUE INDEX IF NOT EXISTS one_active_memory_per_key ON long_memories(key) WHERE active=1;
      CREATE TABLE IF NOT EXISTS blocked_memory_keys(key TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS long_memory_extraction_receipts(turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE);`);
    if(!this.db.prepare('PRAGMA table_info(turns)').all().some(c=>c.name==='conversation_id'))this.db.exec("ALTER TABLE turns ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'");
    if(!this.db.prepare('PRAGMA table_info(background_jobs)').all().some(c=>c.name==='priority'))this.db.exec('ALTER TABLE background_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0');
    this.db.exec('CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id)');
    this.db.exec("UPDATE background_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error='Interrupted' WHERE status='running'");
    this.db.exec("UPDATE background_jobs SET status='done',error=NULL WHERE kind='long_memory.extract' AND turn_id IN (SELECT turn_id FROM long_memory_extraction_receipts)");
  }
  transaction(fn){
    this.db.exec('BEGIN IMMEDIATE');
    try{const r=fn();this.db.exec('COMMIT');return r;}catch(e){this.db.exec('ROLLBACK');throw e;}
  }
  conversations(){return this.db.prepare('SELECT * FROM conversations ORDER BY created_at,id').all();}
  createConversation(title='新会话'){if(typeof title!=='string'||!title.trim()||title.length>120)throw Error('Invalid title');const c={id:randomUUID(),title:title.trim(),created_at:new Date().toISOString()};this.db.prepare('INSERT INTO conversations VALUES(?,?,?)').run(c.id,c.title,c.created_at);return c;}
  requireConversation(id){if(typeof id!=='string'||!this.db.prepare('SELECT 1 FROM conversations WHERE id=?').get(id))throw Error('Unknown conversation');}
  getInstructions(conversationId='default'){this.requireConversation(conversationId);return this.db.prepare('SELECT conversation_id,content,source_turn_id,version,created_at,updated_at FROM conversation_instructions WHERE conversation_id=?').get(conversationId)||null;}
  clearInstructions(conversationId='default'){this.requireConversation(conversationId);return this.db.prepare('DELETE FROM conversation_instructions WHERE conversation_id=?').run(conversationId).changes>0;}
  instructionSourceIds(conversationId='default'){this.requireConversation(conversationId);return this.db.prepare('SELECT source_turn_id FROM conversation_instruction_sources WHERE conversation_id=? ORDER BY created_at,source_turn_id').all(conversationId).map(row=>row.source_turn_id);}
  deleteConversation(id){this.requireConversation(id);return this.transaction(()=>{this.db.prepare('DELETE FROM conversation_instructions WHERE conversation_id=?').run(id);this.db.prepare('DELETE FROM conversation_instruction_sources WHERE conversation_id=?').run(id);this.db.prepare('DELETE FROM turns WHERE conversation_id=?').run(id);if(id!=='default')this.db.prepare('DELETE FROM conversations WHERE id=?').run(id);});}
  requestTurn(requestId){if(typeof requestId!=='string'||!requestId)return null;const row=this.db.prepare('SELECT turn_id FROM turn_requests WHERE request_id=?').get(requestId);return row?this.turn(row.turn_id):null;}
  append(user,assistant,kinds=[],conversationId='default',requestId=null,instructionUpdate=null){
    this.requireConversation(conversationId);
    return this.transaction(()=>{
      if(requestId){const existing=this.db.prepare('SELECT turn_id FROM turn_requests WHERE request_id=?').get(requestId);if(existing)return this.turn(existing.turn_id);}
      const t={id:randomUUID(),user,assistant,created_at:new Date().toISOString(),conversation_id:conversationId};
      this.db.prepare('INSERT INTO turns(id,user,assistant,created_at,conversation_id) VALUES(?,?,?,?,?)').run(t.id,t.user,t.assistant,t.created_at,conversationId);
      if(requestId)this.db.prepare('INSERT INTO turn_requests(request_id,turn_id) VALUES(?,?)').run(requestId,t.id);
      if(instructionUpdate){
        const content=instructionUpdate.content;
        if(typeof content!=='string'||!content.trim()||content.length>16000)throw Error('Invalid session instructions');
        const time=new Date().toISOString();
        this.db.prepare(`INSERT INTO conversation_instructions(conversation_id,content,source_turn_id,version,created_at,updated_at) VALUES(?,?,?,1,?,?)
          ON CONFLICT(conversation_id) DO UPDATE SET content=excluded.content,source_turn_id=excluded.source_turn_id,version=conversation_instructions.version+1,updated_at=excluded.updated_at`).run(conversationId,content.trim(),t.id,time,time);
        this.db.prepare('INSERT OR IGNORE INTO conversation_instruction_sources(conversation_id,source_turn_id,created_at) VALUES(?,?,?)').run(conversationId,t.id,time);
      }
      const insert=this.db.prepare('INSERT INTO background_jobs(turn_id,kind,priority) VALUES(?,?,?)');
      for(const spec of kinds)insert.run(t.id,typeof spec==='string'?spec:spec.kind,typeof spec==='string'?0:spec.priority);
      return t;
    });
  }
  history(limit=12,conversationId='default'){this.requireConversation(conversationId);return this.db.prepare('SELECT id,user,assistant,created_at,conversation_id FROM turns WHERE conversation_id=? ORDER BY rowid DESC LIMIT ?').all(conversationId,limit).reverse();}
  historyPage(limit=80,conversationId='default',before=null){
    this.requireConversation(conversationId);
    if(!Number.isInteger(limit)||limit<1||limit>200)throw Error('Invalid page size');
    if(before!==null&&(!Number.isSafeInteger(before)||before<1))throw Error('Invalid cursor');
    const rows=before===null
      ?this.db.prepare('SELECT rowid AS cursor,id,user,assistant,created_at,conversation_id FROM turns WHERE conversation_id=? ORDER BY rowid DESC LIMIT ?').all(conversationId,limit+1)
      :this.db.prepare('SELECT rowid AS cursor,id,user,assistant,created_at,conversation_id FROM turns WHERE conversation_id=? AND rowid<? ORDER BY rowid DESC LIMIT ?').all(conversationId,before,limit+1);
    const has_more=rows.length>limit,selected=rows.slice(0,limit).reverse();
    return {turns:selected,has_more,before:selected.length?selected[0].cursor:null};
  }
  historyAround(id,limit=80,conversationId='default'){
    this.requireConversation(conversationId);
    if(!Number.isInteger(limit)||limit<2||limit>200)throw Error('Invalid page size');
    const target=this.db.prepare('SELECT rowid AS cursor FROM turns WHERE id=? AND conversation_id=?').get(id,conversationId);
    if(!target)return null;
    const leftCount=Math.floor(limit/2),rightCount=limit-leftCount;
    const left=this.db.prepare('SELECT rowid AS cursor,id,user,assistant,created_at,conversation_id FROM turns WHERE conversation_id=? AND rowid<=? ORDER BY rowid DESC LIMIT ?').all(conversationId,target.cursor,leftCount);
    const right=this.db.prepare('SELECT rowid AS cursor,id,user,assistant,created_at,conversation_id FROM turns WHERE conversation_id=? AND rowid>? ORDER BY rowid ASC LIMIT ?').all(conversationId,target.cursor,rightCount);
    const oldest=left.at(-1)?.cursor??null,newest=right.at(-1)?.cursor??left[0]?.cursor??null;
    const has_more_before=oldest!==null&&!!this.db.prepare('SELECT 1 FROM turns WHERE conversation_id=? AND rowid<? LIMIT 1').get(conversationId,oldest);
    const has_more_after=newest!==null&&!!this.db.prepare('SELECT 1 FROM turns WHERE conversation_id=? AND rowid>? LIMIT 1').get(conversationId,newest);
    return {turns:[...left.reverse(),...right],has_more_before,has_more_after,before:oldest};
  }
  search(query,{from=null,to=null,limit=50,conversationId='default'}={}){
    this.requireConversation(conversationId);
    if(typeof query!=='string'||!query.trim()||query.length>120)throw Error('Invalid search query');
    if(!Number.isInteger(limit)||limit<1||limit>100)throw Error('Invalid search limit');
    const clauses=['conversation_id=?','(instr(lower(user),lower(?))>0 OR instr(lower(assistant),lower(?))>0)'];
    const args=[conversationId,query.trim(),query.trim()];
    if(from){clauses.push('substr(created_at,1,10)>=?');args.push(from);}
    if(to){clauses.push('substr(created_at,1,10)<=?');args.push(to);}
    args.push(limit);
    return this.db.prepare('SELECT rowid AS cursor,id,user,assistant,created_at,conversation_id FROM turns WHERE '+clauses.join(' AND ')+' ORDER BY rowid DESC LIMIT ?').all(...args);
  }
  turn(id){return this.db.prepare('SELECT id,user,assistant,created_at,conversation_id FROM turns WHERE id=?').get(id);}
  jobs(turnId){return turnId?this.db.prepare('SELECT * FROM background_jobs WHERE turn_id=? ORDER BY id').all(turnId):this.db.prepare('SELECT * FROM background_jobs ORDER BY id DESC LIMIT 200').all();}
  claim(){
    return this.transaction(()=>{
      const j=this.db.prepare("SELECT * FROM background_jobs WHERE status='pending' AND attempts<3 ORDER BY priority DESC,id LIMIT 1").get();
      if(!j)return null;
      this.db.prepare("UPDATE background_jobs SET status='running',attempts=attempts+1,error=NULL WHERE id=?").run(j.id);
      return {...j,attempts:j.attempts+1};
    });
  }
  finish(id,error=null){
    this.db.prepare("UPDATE background_jobs SET status=CASE WHEN ? IS NULL THEN 'done' WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error=? WHERE id=? AND status='running'").run(error,error,id);
  }
  jobCounts(){return Object.fromEntries(this.db.prepare('SELECT status,COUNT(*) AS count FROM background_jobs GROUP BY status').all().map(r=>[r.status,r.count]));}
  close(){this.db.close();}
}
