import { useMemo, useState } from 'react';
import { Check, Copy } from 'lucide-react';

/**
 * JSON, highlighted without a highlighter.
 *
 * A tokeniser for one known grammar is about thirty lines; prism or shiki is
 * tens of kilobytes to do the same job on a block this app already knows the
 * shape of. The real constraint is the palette: a monochrome UI has no hue to
 * spend on token types, so these separate by weight - keys bright, strings
 * plain, numbers and literals dim, punctuation dimmest.
 */
const TOKENS =
  /("(?:[^"\\]|\\.)*"\s*:)|("(?:[^"\\]|\\.)*")|(\b-?\d+(?:\.\d+)?\b)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],])/g;

const CLASSES = {
  key: 'text-foreground',
  string: 'text-muted-foreground',
  number: 'text-muted-foreground opacity-80',
  literal: 'text-muted-foreground opacity-80',
  punctuation: 'text-muted-foreground opacity-50',
};

const tokenize = (text) => {
  const parts = [];
  let last = 0;

  // String.matchAll keeps the gaps, which carry the indentation.
  for (const match of text.matchAll(TOKENS)) {
    if (match.index > last) {
      parts.push({ value: text.slice(last, match.index) });
    }

    const [value, key, string, number, literal, punctuation] = match;

    parts.push({
      value,
      kind: key
        ? 'key'
        : string
          ? 'string'
          : number
            ? 'number'
            : literal
              ? 'literal'
              : punctuation
                ? 'punctuation'
                : undefined,
    });

    last = match.index + value.length;
  }

  if (last < text.length) {
    parts.push({ value: text.slice(last) });
  }

  return parts;
};

const JsonBlock = ({ code, prefix, onCopied }) => {
  const parts = useMemo(() => tokenize(code), [code]);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prefix ? `${prefix}\n\n${code}` : code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onCopied?.();
    } catch {
      // Denied outside a secure context; the text is selectable.
    }
  };

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={copy}
        aria-label="Copy request"
        className="absolute right-2 top-2 rounded-md border border-border bg-card p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>

      <pre className="overflow-x-auto rounded-xl border border-border bg-card p-4 pr-12 font-mono text-[11px] leading-relaxed">
        {prefix && (
          <span className="mb-2 block text-muted-foreground opacity-70">
            {prefix}
          </span>
        )}

        {parts.map((part, index) => (
          <span key={index} className={part.kind ? CLASSES[part.kind] : undefined}>
            {part.value}
          </span>
        ))}
      </pre>
    </div>
  );
};

export default JsonBlock;
