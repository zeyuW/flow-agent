import type { ReactNode } from "react";

type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; text: string };

const headingPattern = /^(#{1,3})\s+(.+)$/;
const orderedItemPattern = /^\d+\.\s+(.+)$/;
const unorderedItemPattern = /^[-*]\s+(.+)$/;
const inlinePattern = /(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|https?:\/\/[^\s]+|`[^`]+`|\*\*[^*]+\*\*)/g;

function parseBlocks(content: string): Block[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    const heading = line.match(headingPattern);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length as 1 | 2 | 3, text: heading[2] });
      index += 1;
      continue;
    }
    const item = line.match(orderedItemPattern) ?? line.match(unorderedItemPattern);
    if (item) {
      const ordered = orderedItemPattern.test(line);
      const items: string[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        const nextItem = ordered
          ? current.match(orderedItemPattern)
          : current.match(unorderedItemPattern);
        if (nextItem) {
          items.push(nextItem[1]);
          index += 1;
          continue;
        }
        if (!current) {
          index += 1;
          break;
        }
        if (!items.length) break;
        items[items.length - 1] += ` ${current}`;
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length) {
      const current = lines[index].trim();
      if (
        !current ||
        headingPattern.test(current) ||
        orderedItemPattern.test(current) ||
        unorderedItemPattern.test(current)
      ) {
        break;
      }
      paragraph.push(current);
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
  }
  return blocks;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let offset = 0;
  for (const match of text.matchAll(inlinePattern)) {
    const [value, markdownLink, label, link] = match;
    if (match.index! > offset) {
      nodes.push(text.slice(offset, match.index));
    }
    if (markdownLink) {
      nodes.push(
        <a href={link} key={`${match.index}-link`} rel="noreferrer" target="_blank">
          {label}
        </a>
      );
    } else if (value.startsWith("http")) {
      nodes.push(
        <a href={value} key={`${match.index}-url`} rel="noreferrer" target="_blank">
          {value}
        </a>
      );
    } else if (value.startsWith("`")) {
      nodes.push(<code key={`${match.index}-code`}>{value.slice(1, -1)}</code>);
    } else {
      nodes.push(<strong key={`${match.index}-strong`}>{value.slice(2, -2)}</strong>);
    }
    offset = match.index! + value.length;
  }
  if (offset < text.length) {
    nodes.push(text.slice(offset));
  }
  return nodes;
}

export function MessageContent({ content }: { content: string }) {
  return (
    <div className="message-content">
      {parseBlocks(content).map((block, index) => {
        if (block.kind === "heading") {
          const Heading = `h${block.level}` as "h1" | "h2" | "h3";
          return <Heading key={index}>{renderInline(block.text)}</Heading>;
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </List>
          );
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </div>
  );
}
