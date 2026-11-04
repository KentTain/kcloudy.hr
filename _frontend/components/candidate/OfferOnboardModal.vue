<script setup lang="ts">
/**
 * 办理入职弹窗：已接受 Offer 的入职转化建档（入职日期缺省今日，岗位可选覆盖需求配置）。
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

import { getPositionOptions } from "@/hr/api/reference";
import { getApplicationOffer, onboardOffer } from "@/hr/api/offer";
import type { Application } from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  application: Application | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const hireDate = ref("");
const positionId = ref("");
const positionOptions = ref<{ label: string; value: string }[]>([]);

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  hireDate.value = today();
  positionId.value = "";
  if (!positionOptions.value.length) {
    try {
      const res = await getPositionOptions();
      positionOptions.value = (res.data ?? []).map((item) => ({
        label: item.name,
        value: item.id,
      }));
    } catch {
      positionOptions.value = [];
    }
  }
}, { immediate: true });

async function handleSubmit() {
  const application = props.application;
  if (!application) return;
  submitting.value = true;
  try {
    const offerRes = await getApplicationOffer(application.id);
    const offer = offerRes.data;
    if (!offer) {
      notifyError(new Error("未找到该投递的 Offer 单，请确认 Offer 已发送并接受"));
      return;
    }
    const result = await onboardOffer(offer.id, {
      hire_date: hireDate.value || undefined,
      position_id: positionId.value || undefined,
    });
    notifySuccess(
      `入职建档完成，工号 ${result.data?.employee_no ?? "--"}；申请流转至已入职`,
    );
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "入职转化失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-sm" data-testid="offer-onboard-dialog">
      <DialogHeader>
        <DialogTitle>办理入职</DialogTitle>
        <DialogDescription>
          {{ application?.candidate_name ?? "--" }} · {{ application?.requisition_title ?? "--" }}；建档后自动取号并回填员工档。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>入职日期</Label>
          <Input v-model="hireDate" type="date" data-testid="onboard-hire-date-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>岗位（缺省沿用需求配置）</Label>
          <Select
            v-model="positionId"
            placeholder="沿用需求岗位"
            :options="positionOptions"
            data-testid="onboard-position-select"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="onboard-submit" @click="handleSubmit">
          {{ submitting ? "建档中…" : "确认入职" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
