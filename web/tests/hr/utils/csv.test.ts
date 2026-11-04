/**
 * CSV 解析工具单元测试（员工批量导入）
 */
import { describe, expect, it } from "vitest";

import { parseCsv } from "@/hr/utils/csv";

describe("parseCsv", () => {
  it("解析基本行", () => {
    expect(parseCsv("a,b,c\n1,2,3")).toEqual([
      ["a", "b", "c"],
      ["1", "2", "3"],
    ]);
  });

  it("支持引号内逗号与转义引号", () => {
    expect(parseCsv('name,remark\n"张三","含,逗号"\n"李四","说""你好"""')).toEqual([
      ["name", "remark"],
      ["张三", "含,逗号"],
      ["李四", '说"你好"'],
    ]);
  });

  it("兼容 CRLF 并剔除空行", () => {
    expect(parseCsv("a,b\r\n1,2\r\n\r\n")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("全空行不入结果", () => {
    expect(parseCsv(",,\na,b")).toEqual([["a", "b"]]);
  });
});
