<script setup lang="ts">
/**
 * 渠道发布弹窗：勾选渠道发布需求；内部渠道恒可选，外部按渠道管理凭证状态出项。
 */
import { computed, ref, watch } from "vue";

import { Button } from "@/components";
import { Checkbox } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listChannels, publishRequisition } from "@/hr/api/recruiting";
import {
  CHANNEL_LABELS,
  INTERNAL_CHANNEL,
  type ChannelCard,
  type Requisition,
  type RecruitingChannel,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  requisition: Requisition | null;
}>();

const emit = defineEmits<{ published: [] }>();

const submitting = ref(false);
const selectedChannels = ref<RecruitingChannel[]>([]);
const channelCards = ref<ChannelCard[]>([]);

const alreadyPosted = computed(() => new Set((props.requisition?.postings ?? []).map((p) => p.channel)));

const channelOptions = computed(() => {
  const cards = new Map(channelCards.value.map((card) => [card.channel, card]));
  return (Object.keys(CHANNEL_LABELS) as RecruitingChannel[]).map((channel) => {
    const card = cards.get(channel);
    return {
      channel,
      label: CHANNEL_LABELS[channel],
      available: channel === INTERNAL_CHANNEL || Boolean(card?.configured),
      posted: alreadyPosted.value.has(channel),
    };
  });
});

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  selectedChannels.value = [INTERNAL_CHANNEL];
  try {
    const res = await listChannels();
    channelCards.value = res.data ?? [];
  } catch {
    channelCards.value = [];
  }
}, { immediate: true });

function toggleChannel(channel: RecruitingChannel, checked: boolean) {
  if (checked) {
    if (!selectedChannels.value.includes(channel)) selectedChannels.value.push(channel);
  } else {
    selectedChannels.value = selectedChannels.value.filter((item) => item !== channel);
  }
}

async function handlePublish() {
  if (!props.requisition) return;
  if (!selectedChannels.value.length) {
    notifyError(new Error("请至少选择一个渠道"));
    return;
  }
  submitting.value = true;
  try {
    await publishRequisition(props.requisition.id, selectedChannels.value);
    notifySuccess(
      selectedChannels.value.some((channel) => channel !== INTERNAL_CHANNEL)
        ? "已提交发布，外部渠道发布中"
        : "已发布到站内",
    );
    open.value = false;
    emit("published");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "渠道发布失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-sm" data-testid="requisition-publish-dialog">
      <DialogHeader>
        <DialogTitle>发布到渠道</DialogTitle>
        <DialogDescription>
          {{ requisition?.title ?? "--" }}（{{ requisition?.req_no ?? "--" }}）；外部渠道发布任务完成后回写职位映射。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-2" data-testid="publish-channel-group">
        <label
          v-for="option in channelOptions"
          :key="option.channel"
          class="flex items-center gap-2 text-sm"
          :class="option.available ? '' : 'text-muted-foreground opacity-60'"
        >
          <Checkbox
            :model-value="selectedChannels.includes(option.channel)"
            :disabled="!option.available"
            :data-testid="`publish-channel-${option.channel}`"
            @update:model-value="toggleChannel(option.channel, $event === true)"
          />
          {{ option.label }}
          <span v-if="!option.available" class="text-muted-foreground text-xs">（未配置凭证）</span>
          <span v-else-if="option.posted" class="text-muted-foreground text-xs">（已发布，可重发）</span>
        </label>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="publish-submit" @click="handlePublish">
          {{ submitting ? "发布中…" : "发布" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
