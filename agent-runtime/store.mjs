import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';
export class Store {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, user TEXT NOT NULL, assistant TEXT NOT NULL, created_at TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS sync_state(id INTEGER PRIMARY KEY CHECK(id=1), cursor INTEGER NOT NULL);
      INSERT OR IGNORE INTO sync_state VALUES(1,0);`);
  }
  transaction(fn) {
    this.db.exec('BEGIN IMMEDIATE');
    try { const result=fn(); this.db.exec('COMMIT'); return result; }
    catch(e){ this.db.exec('ROLLBACK'); throw e; }
  }
  append(user, assistant) {
    const t={id:randomUUID(),user,assistant,created_at:new Date().toISOString()};
    this.db.prepare('INSERT INTO turns(id,user,assistant,created_at) VALUES(?,?,?,?)').run(t.id,t.user,t.assistant,t.created_at);
    return t;
  }
  history(limit=12) {
    return this.db.prepare('SELECT id,user,assistant,created_at FROM turns ORDER BY created_at DESC,id DESC LIMIT ?').all(limit).reverse();
  }
  pending() {
    return this.db.prepare('SELECT id,user,assistant,created_at FROM turns WHERE synced=0 ORDER BY created_at,id LIMIT 100').all();
  }
  cursor(){return this.db.prepare('SELECT cursor FROM sync_state WHERE id=1').get().cursor;}
  applySync(ack, turns, cursor) {
    if(!Number.isSafeInteger(cursor)||cursor<this.cursor()) throw Error('Invalid sync cursor');
    this.transaction(()=>{
      const mark=this.db.prepare('UPDATE turns SET synced=1 WHERE id=?');
      const get=this.db.prepare('SELECT user,assistant,created_at FROM turns WHERE id=?');
      const insert=this.db.prepare('INSERT INTO turns(id,user,assistant,created_at,synced) VALUES(?,?,?,?,1)');
      for(const id of ack) mark.run(id);
      for(const t of turns){
        const local=get.get(t.id);
        if(local && ['user','assistant','created_at'].some(k=>local[k]!==t[k])) throw Error('Sync identity conflict');
        if(local) mark.run(t.id); else insert.run(t.id,t.user,t.assistant,t.created_at);
      }
      this.db.prepare('UPDATE sync_state SET cursor=? WHERE id=1').run(cursor);
    });
  }
  close(){this.db.close();}
}
