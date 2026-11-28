function decodeEntities(value){
  const named={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '};
  return value.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi,(whole,entity)=>{
    if(entity[0]==='#'){
      const hex=entity[1]?.toLowerCase()==='x',number=parseInt(entity.slice(hex?2:1),hex?16:10);
      try{return Number.isFinite(number)?String.fromCodePoint(number):whole;}catch{return whole;}
    }
    return named[entity.toLowerCase()]??whole;
  });
}
function htmlText(fragment){
  return decodeEntities(fragment
    .replace(/<br\s*\/?\s*>/gi,'\n')
    .replace(/<\/(?:p|div|li|h[1-6]|blockquote)>/gi,'\n')
    .replace(/<[^>]*>/g,''))
    .replace(/\r/g,'')
    .replace(/[ \t]+\n/g,'\n')
    .replace(/\n{3,}/g,'\n\n')
    .trim();
}
export function parseSource(html){
  const promptMatch=html.match(/<pre\b[^>]*class=["'][^"']*prompt-text[^"']*["'][^>]*>([\s\S]*?)<\/pre>/i);
  if(!promptMatch)throw Error('Could not find .prompt-text in the supplied HTML file');
  const prompt=htmlText(promptMatch[1]);
  const dialogue=html.match(/<section\b[^>]*id=["']dialogue["'][^>]*>([\s\S]*?)<\/section>/i)?.[1]??html;
  const userTurns=[];
  for(const match of dialogue.matchAll(/<article\b[^>]*class=["'][^"']*\buser\b[^"']*["'][^>]*>([\s\S]*?)<\/article>/gi)){
    const article=match[1];
    if(/class=["'][^"']*prompt-details/.test(article))continue;
    const plain=article.match(/<div\b[^>]*class=["'][^"']*\bplain\b[^"']*["'][^>]*>([\s\S]*?)<\/div>/i);
    if(plain){const text=htmlText(plain[1]);if(text)userTurns.push(text);}
  }
  if(!prompt.trim()||!userTurns.length)throw Error('The source HTML did not contain a prompt and user dialogue turns');
  return {prompt,userTurns};
}
