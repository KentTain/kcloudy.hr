/**
 * 极简 CSV 解析（支持引号包裹与引号内逗号/换行；空行剔除）
 */
export function parseCsv(text: string): string[][] {
  const lines: string[][] = [];
  let current: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      current.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      current.push(field);
      field = "";
      if (current.some((cell) => cell !== "")) lines.push(current);
      current = [];
    } else {
      field += char;
    }
  }
  current.push(field);
  if (current.some((cell) => cell !== "")) lines.push(current);
  return lines;
}
