<script setup lang="ts">
/**
 * 合同新签/续签弹窗（续签由后端闭合旧合同区间并生成新合同）
 */
import { ref, watch } from "vue";

import { Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { DateInput, Input, Select, Switch } from "@/components";
import { Label } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createContract, renewContract } from "@/hr/api/contract";
import { CONTRACT_TYPE_OPTIONS, type Contract } from "@/hr/types/employee";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  employeeId: string;
  /** 续签模式的旧合同 */
  renewFrom?: Contract | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const contractNo = ref("");
const contractType = ref<string>("fixed");
const startDate = ref<string>("");
const endDate = ref<string>("");
const company = ref<string>("");
const signedDate = ref<string>("");
const expiryRemind = ref(false);
const remark = ref<string>("");

const isRenew = () => Boolean(props.renewFrom);

watch(open, (value) => {
  if (!value) return;
  contractNo.value = "";
  contractType.value = props.renewFrom?.contract_type ?? "fixed";
  startDate.value = props.renewFrom?.end_date ?? new Date().toISOString().slice(0, 10);
  endDate.value = "";
  company.value = props.renewFrom?.company ?? "";
  signedDate.value = new Date().toISOString().slice(0, 10);
  expiryRemind.value = true;
  remark.value = "";
}, { immediate: true });

async function handleSubmit() {
  if (!contractNo.value.trim() || !startDate.value) {
    notifyError(new Error("请填写合同编号与开始日期"));
    return;
  }
  submitting.value = true;
  try {
    const payload = {
      contract_no: contractNo.value,
      contract_type: contractType.value,
      start_date: startDate.value,
      end_date: endDate.value || undefined,
      company: company.value || undefined,
      signed_date: signedDate.value || undefined,
      expiry_remind: expiryRemind.value,
      remark: remark.value || undefined,
    };
    if (props.renewFrom) {
      await renewContract(props.renewFrom.id, payload);
      notifySuccess("续签成功，旧合同区间已闭合");
    } else {
      await createContract({ employee_id: props.employeeId, ...payload });
      notifySuccess("合同已新签");
    }
    emit("saved");
    open.value = false;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-lg" data-testid="employee-contract-modal">
      <DialogHeader>
        <DialogTitle>{{ isRenew() ? "合同续签" : "新签合同" }}</DialogTitle>
        <DialogDescription>
          {{ isRenew() ? "续签后旧合同区间自动闭合，新合同自此生效。" : "录入新合同信息，保存后生效。" }}
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-4 py-2">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>合同编号 <span class="text-destructive">*</span></Label>
            <Input v-model="contractNo" placeholder="如 HT-2026-001" data-testid="contract-no-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>合同类型</Label>
            <Select v-model="contractType" :options="CONTRACT_TYPE_OPTIONS" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>开始日期 <span class="text-destructive">*</span></Label>
            <DateInput v-model="startDate" data-testid="contract-start-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>结束日期</Label>
            <DateInput v-model="endDate" placeholder="无固定期限可不填" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>签约公司</Label>
            <Input v-model="company" placeholder="签约主体" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>签订日期</Label>
            <DateInput v-model="signedDate" />
          </div>
        </div>
        <div class="flex items-center gap-2">
          <Switch id="contract-expiry-remind" v-model="expiryRemind" />
          <Label for="contract-expiry-remind">到期前提醒（站内信）</Label>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>备注</Label>
          <Input v-model="remark" placeholder="选填" />
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="contract-submit" @click="handleSubmit">
          保存
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
