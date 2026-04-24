const HASHTAG_RE = /(?:^|\s)#([a-zA-Zа-яА-Я][\w\-а-яА-Я]{0,40})/g;

export function extractHashtags(text: string | undefined | null): string[] {
  if (!text) return [];
  const out: string[] = [];
  let m: RegExpExecArray | null;
  HASHTAG_RE.lastIndex = 0;
  while ((m = HASHTAG_RE.exec(text)) !== null) {
    out.push(m[1].toLowerCase());
  }
  return out;
}
