<script setup lang="ts">
/**
 * 候选人详情侧滑：主档头（联系方式/渠道/黑名单/AI 简历解析）+ AI 归一 profile 分区
 * + 投递历史表。profile 为 AI 异步生成，字段缺失时分区整体降级隐藏。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, DescriptionList, Table } from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { getCandidate, parseResume, setBlacklist } from "@/hr/api/candidate";
import { updateApplicationStage } from "@/hr/api/recruiting";
import {
  APPLICATION_STAGE_LABELS,
  APPLICATION_STAGE_VARIANTS,
  CANDIDATE_CHANNEL_LABELS,
  STAGE_TRANSITIONS,
  type Application,
  type ApplicationStage,
  type CandidateDetail,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  candidateId: string | null;
  canWrite: boolean;
  canMerge: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
  /** 点击合并入口（携带主档 id/name） */
  merge: [source: { id: string; name: string }];
}>();

const candidate = ref<CandidateDetail | null>(null);
const loading = ref(false);

interface ProfileEducation {
  school?: string;
  major?: string;
  degree?: string;
}

interface ProfileExperience {
  company?: string;
  title?: string;
  summary?: string;
}

interface ProfileView {
  years: number | null;
  education: ProfileEducation[];
  experiences: ProfileExperience[];
  skills: string[];
  highlights: string;
  risks: string;
}

const EMPTY_PROFILE: ProfileView = {
  years: null,
  education: [],
  experiences: [],
  skills: [],
  highlights: "",
  risks: "",
};

const profileView = computed<ProfileView>(() => {
  const raw = candidate.value?.profile;
  if (!raw || typeof raw !== "object") return EMPTY_PROFILE;
  const record = raw as Record<string, unknown>;
  const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
  const asString = (value: unknown): string => (typeof value === "string" ? value : "");
  return {
    years: typeof record.years === "number" ? record.years : null,
    education: asArray(record.education).filter((item): item is ProfileEducation => !!item && typeof item === "object"),
    experiences: asArray(record.experiences).filter(
      (item): item is ProfileExperience => !!item && typeof item === "object",
    ),
    skills: asArray(record.skills).map((item) => String(item)).filter(Boolean),
    highlights: asString(record.highlights),
    risks: asString(record.risks),
  };
});

const hasProfile = computed(
  () =>
    profileView.value.years !== null ||
    profileView.value.education.length > 0 ||
    profileView.value.experiences.length > 0 ||
    profileView.value.skills.length > 0 ||
    !!profileView.value.highlights ||
    !!profileView.value.risks,
);

async function loadAll() {
  if (!props.candidateId) return;
  loading.value = true;
  try {
    const res = await getCandidate(props.candidateId);
    candidate.value = res.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人详情加载失败"));
    candidate.value = null;
  } finally {
    loading.value = false;
  }
}

watch(open, (value) => {
  if (!value) return;
  candidate.value = null;
  void loadAll();
});

async function toggleBlacklist() {
  const item = candidate.value;
  if (!item) return;
  const next = !item.is_blacklist;
  if (
    next &&
    !(await confirmAction(`确定将「${item.name}」加入黑名单？黑名单候选人默认不在卡片流中展示。`))
  ) {
    return;
  }
  try {
    await setBlacklist(item.id, next);
    notifySuccess(next ? "已加入黑名单" : "已移出黑名单");
    await loadAll();
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "黑名单操作失败"));
  }
}

async function reparseResume() {
  const item = candidate.value;
  if (!item) return;
  if (!(await confirmAction("重新解析简历为异步任务，解析完成后 AI 档案将自动更新。继续？"))) return;
  try {
    await parseResume(item.id);
    notifySuccess("简历解析任务已提交，完成后档案自动更新");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "简历解析提交失败"));
  }
}

const infoItems = computed(() => {
  const item = candidate.value;
  if (!item) return [];
  return [
    { label: "手机号", value: item.phone || "--" },
    { label: "邮箱", value: item.email || "--" },
    { label: "来源渠道", value: CANDIDATE_CHANNEL_LABELS[item.source_channel] ?? item.source_channel },
    { label: "工作年限", value: profileView.value.years === null ? "--" : `${profileView.value.years} 年` },
    { label: "简历文件", value: item.resume_file || "--" },
  ];
});

const applicationColumns = [
  { key: "requisition", title: "需求", width: "180px" },
  { key: "stage", title: "当前阶段", width: "110px" },
  { key: "match_score", title: "匹配分", width: "80px" },
  { key: "apply_time", title: "投递时间", width: "110px" },
  { key: "actions", title: "流转", width: "160px", align: "right" as const },
];

async function handleStageChange(application: Application, target: ApplicationStage) {
  try {
    await updateApplicationStage(application.id, target);
    notifySuccess(`已流转至「${APPLICATION_STAGE_LABELS[target]}」`);
    await loadAll();
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "阶段流转失败"));
  }
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent side="right" class="flex w-full flex-col gap-0 overflow-hidden sm:max-w-2xl" data-testid="candidate-detail-sheet">
      <SheetHeader class="shrink-0 border-b px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <SheetTitle class="flex items-center gap-2" data-testid="candidate-detail-name">
              {{ candidate?.name ?? "候选人详情" }}
              <Badge v-if="candidate?.is_blacklist" variant="destructive">黑名单</Badge>
            </SheetTitle>
            <SheetDescription class="mt-1">
              来源：{{ candidate ? (CANDIDATE_CHANNEL_LABELS[candidate.source_channel] ?? candidate.source_channel) : "--" }}
            </SheetDescription>
          </div>
          <div v-if="canWrite && candidate" class="flex shrink-0 flex-wrap justify-end gap-2">
            <Button variant="outline" size="sm" data-testid="detail-toggle-blacklist" @click="toggleBlacklist">
              {{ candidate.is_blacklist ? "移出黑名单" : "加入黑名单" }}
            </Button>
            <Button variant="outline" size="sm" data-testid="detail-reparse" @click="reparseResume">
              AI 重新解析
            </Button>
            <Button
              v-if="canMerge"
              variant="outline"
              size="sm"
              data-testid="detail-merge"
              @click="emit('merge', { id: candidate.id, name: candidate.name })"
            >
              合并
            </Button>
          </div>
        </div>
      </SheetHeader>

      <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-5 py-4">
        <!-- 主档信息 -->
        <DescriptionList :items="infoItems" :columns="3" data-testid="candidate-detail-info" />

        <!-- AI 归一档案（异步解析产物，未生成分区降级隐藏） -->
        <div v-if="hasProfile" class="flex flex-col gap-3" data-testid="candidate-profile">
          <p class="text-muted-foreground text-xs font-medium">AI 档案</p>
          <div v-if="profileView.highlights" class="flex flex-col gap-1">
            <p class="text-xs font-medium">亮点</p>
            <p class="text-sm whitespace-pre-wrap">{{ profileView.highlights }}</p>
          </div>
          <div v-if="profileView.risks" class="flex flex-col gap-1">
            <p class="text-xs font-medium">风险提示</p>
            <p class="text-sm whitespace-pre-wrap">{{ profileView.risks }}</p>
          </div>
          <div v-if="profileView.skills.length" class="flex flex-col gap-1">
            <p class="text-xs font-medium">技能</p>
            <div class="flex flex-wrap gap-1.5">
              <Badge v-for="skill in profileView.skills" :key="skill" variant="secondary">{{ skill }}</Badge>
            </div>
          </div>
          <div v-if="profileView.education.length" class="flex flex-col gap-1">
            <p class="text-xs font-medium">教育经历</p>
            <div
              v-for="(edu, index) in profileView.education"
              :key="index"
              class="text-sm"
              :data-testid="`profile-education-${index}`"
            >
              {{ [edu.school, edu.major, edu.degree].filter(Boolean).join(" · ") || "--" }}
            </div>
          </div>
          <div v-if="profileView.experiences.length" class="flex flex-col gap-1">
            <p class="text-xs font-medium">工作经历</p>
            <div
              v-for="(exp, index) in profileView.experiences"
              :key="index"
              class="flex flex-col gap-0.5 rounded-md border px-3 py-2"
              :data-testid="`profile-experience-${index}`"
            >
              <span class="text-sm font-medium">{{ [exp.company, exp.title].filter(Boolean).join(" · ") || "--" }}</span>
              <span v-if="exp.summary" class="text-muted-foreground text-xs">{{ exp.summary }}</span>
            </div>
          </div>
        </div>

        <!-- 投递历史 -->
        <div class="flex flex-col gap-2">
          <p class="text-muted-foreground text-xs font-medium">投递历史</p>
          <Table
            :columns="applicationColumns"
            :data="candidate?.applications ?? []"
            :loading="loading"
            empty-text="暂无投递记录"
            data-testid="candidate-applications-table"
          >
            <template #requisition="{ row }">
              {{ (row as Application).requisition_title ?? "--" }}
            </template>
            <template #stage="{ row }">
              <Badge :variant="APPLICATION_STAGE_VARIANTS[(row as Application).stage]">
                {{ APPLICATION_STAGE_LABELS[(row as Application).stage] ?? (row as Application).stage }}
              </Badge>
            </template>
            <template #match_score="{ row }">
              {{ (row as Application).match_score === null ? "--" : (row as Application).match_score }}
            </template>
            <template #apply_time="{ row }">
              {{ (row as Application).apply_time?.slice(0, 10) ?? "--" }}
            </template>
            <template #actions="{ row }">
              <div class="flex flex-wrap justify-end gap-1">
                <Button
                  v-for="target in STAGE_TRANSITIONS[(row as Application).stage]"
                  :key="target"
                  variant="link"
                  size="sm"
                  class="h-auto p-0"
                  :class="target === 'rejected' || target === 'withdrawn' ? 'text-destructive' : ''"
                  :data-testid="`detail-stage-${(row as Application).id}-${target}`"
                  @click="handleStageChange(row as Application, target)"
                >
                  {{ APPLICATION_STAGE_LABELS[target] }}
                </Button>
                <span v-if="!STAGE_TRANSITIONS[(row as Application).stage].length" class="text-muted-foreground text-xs">
                  --
                </span>
              </div>
            </template>
          </Table>
        </div>
      </div>
    </SheetContent>
  </Sheet>
</template>
