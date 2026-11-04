<script setup lang="ts">
/**
 * 发起 Offer 弹窗：录入定薪方案快照（月薪基数 + 有效期）→ 创建 Offer 单并立即发送
 * （发送后申请自动流转至已发 Offer）。
 */
import { ref, watch } from "vue";

import { Button, Input } from "@/components";
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

import { createOffer, sendOffer } from "@/hr/api/offer";
import type { Application } from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  application: Application | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const baseMonthly = ref("");
const validUntil = ref("");

watch(open, (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  baseMonthly.value = "";
  validUntil.value = "";
}, { immediate: true });

async function handleSubmit() {
  const application = props.application;
  if (!application) return;
  const amount = Number(baseMonthly.value);
  if (!Number.isFinite(amount) || amount <= 0) {
    notifyError(new Error("请填写有效的月薪数额"));
    return;
  }
  submitting.value = true;
  try {
    const created = await createOffer({
      application_id: application.id,
      salary_snapshot: { base_monthly: amount },
      valid_until: validUntil.value || undefined,
    });
    await sendOffer(created.data.id);
    notifySuccess("Offer 已发送，申请进入已发 Offer");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "Offer 发送失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-sm" data-testid="offer-form-dialog">
      <DialogHeader>
        <DialogTitle>发起 Offer</DialogTitle>
        <DialogDescription>
          {{ application?.candidate_name ?? "--" }} · {{ application?.requisition_title ?? "--" }}；发送后申请置为已发 Offer。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>月薪基数（元）*</Label>
          <Input v-model="baseMonthly" type="number" min="0" placeholder="定薪快照 base_monthly" data-testid="offer-base-monthly-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>有效期至</Label>
          <Input v-model="validUntil" type="date" data-testid="offer-valid-until-input" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="offer-submit" @click="handleSubmit">
          {{ submitting ? "发送中…" : "创建并发送" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
