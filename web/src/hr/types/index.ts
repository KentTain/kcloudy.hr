/**
 * hr 模块前端类型
 *
 * 约定：手写 interface 对齐后端 Pydantic Response 模型（snake_case 同名同义，
 * 无 codegen）；DTO 命名遵循 web/AGENTS.md（{Entity}Query/{Entity}Create/
 * {Entity}Update/{Entity}Response）；分页信封为 ApiResponse（data 裸数组 +
 * 顶层 total/stats），处理见 @/hr/api/shared。各域类型随阶段 7 页面批次增量补充。
 */

/** 分页查询参数（后端 page/page_size 语义，均 1 起始） */
export interface PageQuery {
  page?: number;
  page_size?: number;
}
