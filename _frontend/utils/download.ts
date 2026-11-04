/**
 * base64 文件下载（报表导出/标准代发导出同款：后端返回 {filename, content_base64}）
 */
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export function downloadBase64File(filename: string, contentBase64: string, mime: string = XLSX_MIME): void {
  const binary = atob(contentBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
