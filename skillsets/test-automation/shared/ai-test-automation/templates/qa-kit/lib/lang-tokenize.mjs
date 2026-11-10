/** Blank comments and string bodies; preserve length and newlines for assertion binding. */

function pyPrefixIsRaw(source, quoteIndex) {
  let j = quoteIndex - 1;
  while (j >= 0 && /[rRuUbBfFuU]/.test(source[j])) j--;
  return /r/i.test(source.slice(j + 1, quoteIndex));
}

function csharpAtOrDollarBefore(source, i) {
  let j = i - 1;
  while (j >= 0 && /[@$]/.test(source[j])) j--;
  const seg = source.slice(j + 1, i);
  return { at: seg.includes('@'), dollar: seg.includes('$') };
}

function isHashLineComment(source, i) {
  if (source[i] !== '#') return false;
  const n = source[i + 1];
  if (n && /[a-zA-Z_]/.test(n)) {
    const word = source.slice(i + 1).match(/^[a-zA-Z_][\w]*/)?.[0] ?? '';
    if (/^(if|elif|else|endif|region|endregion|pragma|line|warning|error|nullable|define|undef)$/.test(word)) {
      return false;
    }
    let j = i - 1;
    while (j >= 0 && /\s/.test(source[j])) j--;
    if (source[j] === '{') return false;
  }
  return true;
}

function skipQuotedContent(source, pos, quote, opts) {
  const { triple, pyRaw, verbatim, csharpRaw } = opts;
  while (pos < source.length) {
    const c = source[pos];
    const n = source[pos + 1];
    if (triple) {
      if (c === '\\' && !pyRaw) {
        pos += 2;
        continue;
      }
      if (c === quote) {
        let count = 0;
        while (source[pos + count] === quote) count++;
        if (count >= 3) return pos + 3;
        pos += count;
        continue;
      }
      pos++;
      continue;
    }
    if (verbatim || csharpRaw) {
      if (c === '"' && n === '"') {
        pos += 2;
        continue;
      }
      if (c === quote) return pos + 1;
      pos++;
      continue;
    }
    if (pyRaw) {
      if (c === quote) return pos + 1;
      if (c === '\\' && n === quote) {
        pos += 2;
        continue;
      }
      pos++;
      continue;
    }
    if (c === '\\') {
      pos += 2;
      continue;
    }
    if (c === quote) return pos + 1;
    pos++;
  }
  return source.length;
}

function skipJsTemplate(source, pos) {
  while (pos < source.length) {
    const c = source[pos];
    const n = source[pos + 1];
    if (c === '\\') {
      pos += 2;
      continue;
    }
    if (c === '$' && n === '{') {
      pos += 2;
      let depth = 1;
      while (pos < source.length && depth > 0) {
        const ch = source[pos];
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        else {
          const litEnd = skipLiteral(source, pos);
          if (litEnd > pos) {
            pos = litEnd;
            continue;
          }
        }
        pos++;
      }
      continue;
    }
    if (c === '`') return pos + 1;
    pos++;
  }
  return source.length;
}

function skipJsRegex(source, i) {
  if (source[i] !== '/') return null;
  let pos = i + 1;
  let inClass = false;
  while (pos < source.length) {
    const c = source[pos];
    if (c === '\\') {
      pos += 2;
      continue;
    }
    if (c === '[') inClass = true;
    else if (c === ']' && inClass) inClass = false;
    else if (c === '/' && !inClass) {
      pos++;
      while (pos < source.length && /[dgimsuvy]/i.test(source[pos])) pos++;
      return pos;
    }
    pos++;
  }
  return null;
}

function skipLiteral(source, i) {
  const c = source[i];
  const n = source[i + 1];
  const p = source[i + 2];
  if (c === '`') return skipJsTemplate(source, i + 1);
  if ((c === "'" || c === '"') && n === c && p === c) {
    const pyRaw = pyPrefixIsRaw(source, i);
    return skipQuotedContent(source, i + 3, c, { triple: true, pyRaw });
  }
  if (c === '"') {
    let qCount = 0;
    while (source[i + qCount] === '"') qCount++;
    if (qCount >= 3) {
      return skipQuotedContent(source, i + 3, '"', { triple: true, csharpRaw: true });
    }
    const { at } = csharpAtOrDollarBefore(source, i);
    if (at) return skipQuotedContent(source, i + 1, '"', { verbatim: true });
    return skipQuotedContent(source, i + 1, '"', {});
  }
  if (c === "'") {
    const pyRaw = pyPrefixIsRaw(source, i);
    return skipQuotedContent(source, i + 1, "'", { pyRaw });
  }
  return i;
}

export function tokenize(source) {
  let out = '';
  let i = 0;
  let state = 'code';
  while (i < source.length) {
    const c = source[i];
    const n = source[i + 1];
    if (state === 'code') {
      if (isHashLineComment(source, i)) {
        out += ' ';
        i++;
        state = 'line';
        continue;
      }
      if (c === '/' && n === '/') {
        out += '  ';
        i += 2;
        state = 'line';
        continue;
      }
      if (c === '/' && n === '*') {
        out += '  ';
        i += 2;
        state = 'block';
        continue;
      }
      const regexEnd = c === '/' && /[=([,:;!&|?>\s]/.test(source[i - 1] ?? '(') ? skipJsRegex(source, i) : null;
      if (regexEnd) {
        out += ' '.repeat(regexEnd - i);
        i = regexEnd;
        continue;
      }
      if (c === '"' || c === "'" || c === '`') {
        const end = skipLiteral(source, i);
        out += ' '.repeat(end - i);
        i = end;
        continue;
      }
      out += c;
      i++;
      continue;
    }
    if (state === 'line') {
      if (c === '\n') {
        out += '\n';
        i++;
        state = 'code';
      } else {
        out += ' ';
        i++;
      }
      continue;
    }
    if (state === 'block') {
      if (c === '*' && n === '/') {
        out += '  ';
        i += 2;
        state = 'code';
      } else {
        out += c === '\n' ? '\n' : ' ';
        i++;
      }
      continue;
    }
  }
  return out;
}
