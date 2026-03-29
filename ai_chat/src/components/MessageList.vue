<template>
  <div ref="containerRef" class="flex flex-col gap-4 px-4 py-4 overflow-y-auto">
    <template v-for="(message, i) in messages" :key="i">
      <MessageBubble :message="message" @option="$emit('option', $event)" />
    </template>

    <!-- Loading dots -->
    <div v-if="loading" class="flex justify-start">
      <div class="w-7 h-7 flex items-center justify-center mr-2 mt-1 shrink-0">
        <RevenyuCut class="w-5 h-5" />
      </div>
      <div class="bg-brand-light rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1 items-center">
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 0ms" />
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 150ms" />
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 300ms" />
      </div>
    </div>

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
import RevenyuCut from "./RevenyuCut.vue";
import RevenyuLogo from "./RevenyuLogo.vue";

defineProps({
  messages: { type: Array, required: true },
  loading: { type: Boolean, default: false },
});

defineEmits(["option"]);

const containerRef = ref(null);

function scrollToBottom() {
  const el = containerRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

defineExpose({ scrollToBottom });
</script>
