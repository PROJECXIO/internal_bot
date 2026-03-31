<template>
  <div ref="containerRef" class="flex flex-col gap-4 px-4 py-4 overflow-y-auto" @scroll="onScroll">
    <template v-for="(message, i) in messages" :key="i">
      <MessageBubble :message="message" @option="$emit('option', $event)" />
    </template>

    <!-- Progress timeline (replaces static bouncing dots) -->
    <ProgressTimeline v-if="loading" :steps="progressSteps" />

    <!-- Empty state -->
    <div
      v-if="messages.length === 0 && !loading"
      class="flex-1 flex flex-col items-center justify-center text-center py-16"
    >
      <RevenyuLogo class="text-gray-900 mb-4" />
      <p class="text-sm font-medium text-gray-500">How can I help you?</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import MessageBubble from "./MessageBubble.vue";
import ProgressTimeline from "./ProgressTimeline.vue";
import RevenyuLogo from "./RevenyuLogo.vue";

defineProps({
  messages: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  progressSteps: { type: Array, default: () => [] },
});

defineEmits(["option"]);

const containerRef = ref(null);
const isLockedToBottom = ref(true);

function onScroll() {
  const el = containerRef.value;
  if (!el) return;
  isLockedToBottom.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
}

function scrollToBottom() {
  const el = containerRef.value;
  if (el && isLockedToBottom.value) el.scrollTop = el.scrollHeight;
}

defineExpose({ scrollToBottom });
</script>
