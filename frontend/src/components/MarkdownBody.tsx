import { useMemo, type ReactNode } from "react";

function inlineFormat(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      parts.push(<code key={key++}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("*")) {
      parts.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
  }

  if (last < text.length) parts.push(text.slice(last));
  return parts.length ? parts : [text];
}

type Block =
  | { type: "h2"; text: string }
  | { type: "h3"; text: string }
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "quote"; text: string }
  | { type: "code"; text: string }
  | { type: "hr" }
  | { type: "table"; header: string[]; rows: string[][] };

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|");
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  if (!isTableRow(trimmed)) return false;
  return trimmed
    .slice(1, -1)
    .split("|")
    .every((cell) => /^[\s:|-]+$/.test(cell.trim()));
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
}

function isBlockStarter(line: string): boolean {
  const trimmed = line.trim();
  return (
    !trimmed ||
    trimmed.startsWith("## ") ||
    trimmed.startsWith("### ") ||
    trimmed.startsWith("> ") ||
    /^[-*] /.test(trimmed) ||
    /^\d+\. /.test(trimmed) ||
    trimmed.startsWith("```") ||
    /^-{3,}$/.test(trimmed) ||
    /^\*{3,}$/.test(trimmed) ||
    isTableRow(trimmed)
  );
}

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "code", text: codeLines.join("\n") });
      i += 1;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      blocks.push({ type: "h2", text: trimmed.slice(3).trim() });
      i += 1;
      continue;
    }

    if (trimmed.startsWith("### ")) {
      blocks.push({ type: "h3", text: trimmed.slice(4).trim() });
      i += 1;
      continue;
    }

    if (trimmed.startsWith("> ")) {
      blocks.push({ type: "quote", text: trimmed.slice(2).trim() });
      i += 1;
      continue;
    }

    if (/^-{3,}$/.test(trimmed) || /^\*{3,}$/.test(trimmed)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    if (isTableRow(trimmed) && !isTableSeparator(trimmed)) {
      const header = parseTableRow(line);
      i += 1;
      if (i < lines.length && isTableSeparator(lines[i])) {
        i += 1;
      }
      const rows: string[][] = [];
      while (i < lines.length) {
        const row = lines[i].trim();
        if (!isTableRow(row) || isTableSeparator(row)) break;
        rows.push(parseTableRow(lines[i]));
        i += 1;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    if (/^[-*] /.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*] /, ""));
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\d+\. /.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s*/, ""));
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const para: string[] = [trimmed];
    i += 1;
    while (i < lines.length) {
      const next = lines[i].trim();
      if (isBlockStarter(next)) break;
      para.push(next);
      i += 1;
    }
    blocks.push({ type: "p", text: para.join(" ") });
  }

  return blocks;
}

export function MarkdownBody({ text }: { text: string }) {
  const blocks = useMemo(() => parseBlocks(text), [text]);

  return (
    <div className="md">
      {blocks.map((block, idx) => {
        if (block.type === "h2") {
          return (
            <h2 className="md-h2" key={idx}>
              {inlineFormat(block.text)}
            </h2>
          );
        }
        if (block.type === "h3") {
          return (
            <h3 className="md-h3" key={idx}>
              {inlineFormat(block.text)}
            </h3>
          );
        }
        if (block.type === "quote") {
          return (
            <blockquote className="md-quote" key={idx}>
              {inlineFormat(block.text)}
            </blockquote>
          );
        }
        if (block.type === "hr") {
          return <hr className="md-hr" key={idx} />;
        }
        if (block.type === "table") {
          return (
            <div className="md-table-wrap" key={idx}>
              <table className="md-table">
                <thead>
                  <tr>
                    {block.header.map((cell, j) => (
                      <th key={j}>{inlineFormat(cell)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIdx) => (
                    <tr key={rowIdx}>
                      {row.map((cell, cellIdx) => (
                        <td key={cellIdx}>{inlineFormat(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "ul") {
          return (
            <ul className="md-ul" key={idx}>
              {block.items.map((item, j) => (
                <li key={j}>{inlineFormat(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol className="md-ol" key={idx}>
              {block.items.map((item, j) => (
                <li key={j}>{inlineFormat(item)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === "code") {
          return (
            <pre className="md-pre" key={idx}>
              <code>{block.text}</code>
            </pre>
          );
        }
        return (
          <p className="md-p" key={idx}>
            {inlineFormat(block.text)}
          </p>
        );
      })}
    </div>
  );
}
