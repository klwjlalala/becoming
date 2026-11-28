import {mkdirSync,writeFileSync,readFileSync,unlinkSync,existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {randomUUID} from 'node:crypto';

const TYPES={
  'image/png':{extension:'png',valid:b=>b.length>=8&&b.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))},
  'image/jpeg':{extension:'jpg',valid:b=>b.length>=3&&b[0]===255&&b[1]===216&&b[2]===255},
  'image/webp':{extension:'webp',valid:b=>b.length>=12&&b.toString('ascii',0,4)==='RIFF'&&b.toString('ascii',8,12)==='WEBP'}
};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class AssetStore{
  constructor(store,directory){
    this.store=store;this.directory=resolve(directory);mkdirSync(this.directory,{recursive:true,mode:0o700});
    this.store.db.exec(`CREATE TABLE IF NOT EXISTS assets(
      id TEXT PRIMARY KEY,
      file_name TEXT NOT NULL UNIQUE,
      mime_type TEXT NOT NULL CHECK(mime_type IN ('image/png','image/jpeg','image/webp')),
      size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<=15000000),
      created_at TEXT NOT NULL
    )`);
  }
  save(buffer,mimeType){
    if(!Buffer.isBuffer(buffer)||!buffer.length||buffer.length>15000000)throw Error('Invalid asset bytes');
    const type=TYPES[mimeType];if(!type||!type.valid(buffer))throw Error('Unsupported or invalid image format');
    const id=randomUUID(),fileName=id+'.'+type.extension,path=join(this.directory,fileName),createdAt=new Date().toISOString();
    writeFileSync(path,buffer,{flag:'wx',mode:0o600});
    try{
      this.store.db.prepare('INSERT INTO assets(id,file_name,mime_type,size_bytes,created_at) VALUES(?,?,?,?,?)').run(id,fileName,mimeType,buffer.length,createdAt);
      return {id,mime_type:mimeType,size_bytes:buffer.length,created_at:createdAt};
    }catch(error){try{unlinkSync(path);}catch{}throw error;}
  }
  get(id){
    if(typeof id!=='string'||!UUID.test(id))return null;
    const row=this.store.db.prepare('SELECT id,file_name,mime_type,size_bytes,created_at FROM assets WHERE id=?').get(id);
    if(!row||row.file_name!==row.id+'.'+TYPES[row.mime_type]?.extension)return null;
    const path=join(this.directory,row.file_name);
    if(!existsSync(path))return null;
    return {...row,path};
  }
  read(id){
    const asset=this.get(id);if(!asset)return null;
    const buffer=readFileSync(asset.path);
    if(buffer.length!==asset.size_bytes||!TYPES[asset.mime_type]?.valid(buffer))return null;
    return {asset,buffer};
  }
}
