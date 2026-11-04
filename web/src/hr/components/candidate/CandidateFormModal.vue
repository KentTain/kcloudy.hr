<script setup lang="ts">
/**
 * 手工录入候选人弹窗：主档字段 + 关联需求（关联时同步产生待初筛投递）。
 */
import { ref, watch } from "vue";

import { Button, Input, Select } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listRequisitions } from "@/hr/api/recruiting";
import { createCandidate } from "@/hr/api/candidate";
import { CANDIDATE_CHANNEL_OPTIONS } from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const name = ref("");
const phone = ref("");
const email = ref("");
const sourceChannel = ref("manual");
const requisitionId = ref("__none__");

const requisitionOptions = ref<{ value: string; label: string }[]>([]);

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  name.value = "";
  phone.value = "";
  email.value = "";
  sourceChannel.value = "manual";
  requisitionId.value = "__none__";
  try {
    const res = await listRequisitions({ page: 1, page_size: 100 });
    requisitionOptions.value = [
      { value: "__none__", label: "暂不关联需求" },
      ...(res.data ?? [])
        .filter((item) => item.status !== "closed")
        .map((item) => ({ value: item.id, label: `${item.title}（${item.req_no}）` })),
    ];
  } catch {
    requisitionOptions.value = [{ value: "__none__", label: "暂不关联需求" }];
  }
}, { immediate: true });

async function handleSubmit() {
  if (!name.value.trim()) {
    notifyError(new Error("请填写候选人姓名"));
    return;
  }
  submitting.value = true;
  try {
    const result = await createCandidate({
      name: name.value.trim(),
      phone: phone.value.trim() || undefined,
      email: email.value.trim() || undefined,
      source_channel: sourceChannel.value,
      requisition_id: requisitionId.value === "__none__" ? undefined : requisitionId.value,
    });
    notifySuccess(
      result.data?.application ? "候选人已录入并产生投递" : "候选人已录入",
    );
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人录入失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="candidate-form-dialog">
      <DialogHeader>
        <DialogTitle>手工录入候选人</DialogTitle>
        <DialogDescription>关联需求后立即产生一条待初筛投递；内推免凭证。</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>姓名 *</Label>
          <Input v-model="name" placeholder="候选人姓名" data-testid="candidate-name-input" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>手机号</Label>
            <Input v-model="phone" placeholder="用于重复档识别" data-testid="candidate-phone-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>邮箱</Label>
            <Input v-model="email" data-testid="candidate-email-input" />
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>来源渠道</Label>
          <Select v-model="sourceChannel" :options="CANDIDATE_CHANNEL_OPTIONS" data-testid="candidate-channel-select" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>关联需求</Label>
          <Select v-model="requisitionId" :options="requisitionOptions" data-testid="candidate-requisition-select" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="candidate-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "录入" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
