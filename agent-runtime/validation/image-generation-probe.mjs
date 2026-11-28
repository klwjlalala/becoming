import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {Gateway} from '../agent.mjs';

const output=resolve(process.env.IMAGE_PROBE_REPORT||'agent-runtime/artifacts/image-generation-probe.json');
const report={test:'image-generation-provider-probe'};
const gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
try{
  const prompt=process.env.IMAGE_PROBE_PROMPT||'A calm mountain viewpoint above a distant city at sunrise, atmospheric editorial photography, no text.';
  const image=await gateway.generateImage({prompt,size:'1024x1024'});
  const extension=image.mime_type==='image/png'?'png':image.mime_type==='image/jpeg'?'jpg':'webp';
  const imagePath=output.replace(/\.json$/i,'.'+extension);
  mkdirSync(dirname(output),{recursive:true});
  writeFileSync(imagePath,image.buffer);
  report.status='supported';
  report.mime_type=image.mime_type;
  report.size_bytes=image.buffer.length;
  report.image_artifact=imagePath;
  report.revised_prompt=image.revised_prompt;
}catch(error){
  report.status='failed';
  report.error=error.message;
  process.exitCode=1;
}finally{
  mkdirSync(dirname(output),{recursive:true});
  writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}
