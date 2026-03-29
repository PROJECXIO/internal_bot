<template>
  <div class="px-4 py-3 bg-white">
    <div
      class="flex items-end gap-2 border border-gray-200 rounded-2xl px-3 py-2 focus-within:border-brand transition-colors"
    >
      <textarea
        ref="textareaRef"
        v-model="model"
        placeholder="Ask anything..."
        rows="1"
        :disabled="loading || disabled"
        class="flex-1 resize-none border-none outline-none focus:ring-0 text-sm bg-transparent py-1 max-h-32 leading-relaxed placeholder:text-gray-400"
        @keydown.enter.exact.prevent="handleEnter"
        @input="autoResize"
      />
      <button
        :disabled="loading || disabled || !model.trim()"
        class="shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors"
        :class="
          loading || !model.trim()
            ? 'bg-gray-100 text-gray-300 cursor-not-allowed'
            : 'bg-brand text-white hover:bg-brand-dark cursor-pointer'
        "
        @click="emit('send')"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="w-4 h-4"
        >
          <path d="m5 12 7-7 7 7" />
          <path d="M12 19V5" />
        </svg>
      </button>
    </div>
    <p class="text-center text-xs text-gray-300 mt-2">
      Press Enter to send &middot; Shift+Enter for new line
    </p>
  </div>
</template>

<script setup>
import { ref, nextTick } from "vue";

const model = defineModel({ required: true });
const emit = defineEmits(["send"]);

defineProps({ loading: Boolean, disabled: Boolean });

const textareaRef = ref(null);

function handleEnter() {
  emit("send");
}

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  });
}
</script>
