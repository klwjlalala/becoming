import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
export class Store {
  constructor(path){
    this.db=new DatabaseSync(path);
    this.db.exec(`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,user TEXT NOT NULL,assistant TEXT NOT NULL,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS background_jobs(id INTEGER PRIMARY KEY,turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,error TEXT, UNIQUE(turn_id,kind));
      CREATE TABLE IF NOT EXISTS long_memories(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT NOT NULL,category TEXT NOT NULL CHECK(category IN ('fact','experience','subjective')),quote TEXT NOT NULL,source_turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
      CREATE UNIQUE INDEX IF NOT EXISTS one_active_memory_per_key ON long_memories(key) WHERE active=1;
      CREATE TABLE IF NOT EXISTS blocked_memory_keys(key TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS long_memory_extraction_receipts(turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE);`);
    this.db.exec("UPDATE background_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error='Interrupted' WHERE status='running'");
    this.db.exec("UPDATE background_jobs SET status='done',error=NULL WHERE kind='long_memory.extract' AND turn_id IN (SELECT turn_id FROM long_memory_extraction_receipts)");
  }
  transaction(fn){
    this.db.exec('BEGIN IMMEDIATE');
    try{const r=fn();this.db.exec('COMMIT');return r;}catch(e){this.db.exec('ROLLBACK');throw e;}
  }
  append(user,assistant,kinds=[]){
    const t={id:randomUUID(),user,assistant,created_at:new Date().toISOString()};
    return this.transaction(()=>{
      this.db.prepare('INSERT INTO turns(id,user,assistant,created_at) VALUES(?,?,?,?)').run(t.id,t.user,t.assistant,t.created_at);
      const insert=this.db.prepare('INSERT INTO background_jobs(turn_id,kind) VALUES(?,?)');
      for(const kind of kinds)insert.run(t.id,kind);
      return t;
    });
  }
  history(limit=12){return this.db.prepare('SELECT id,user,assistant,created_at FROM turns ORDER BY rowid DESC LIMIT ?').all(limit).reverse();}
  turn(id){return this.db.prepare('SELECT id,user,assistant,created_at FROM turns WHERE id=?').get(id);}
  jobs(turnId){return turnId?this.db.prepare('SELECT * FROM background_jobs WHERE turn_id=? ORDER BY id').all(turnId):this.db.prepare('SELECT * FROM background_jobs ORDER BY id DESC LIMIT 200').all();}
  claim(){
    return this.transaction(()=>{
      const j=this.db.prepare("SELECT * FROM background_jobs WHERE status='pending' AND attempts<3 ORDER BY id LIMIT 1").get();
      if(!j)return null;
      this.db.prepare("UPDATE background_jobs SET status='running',attempts=attempts+1,error=NULL WHERE id=?").run(j.id);
      return {...j,attempts:j.attempts+1};
    });
  }
  finish(id,error=null){
    this.db.prepare("UPDATE background_jobs SET status=CASE WHEN ? IS NULL THEN 'done' WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error=? WHERE id=? AND status='running'").run(error,error,id);
  }
  close(){this.db.close();}
}
