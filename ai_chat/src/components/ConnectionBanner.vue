<template>
  <Transition name="banner">
    <div
      v-if="show"
      class="flex items-center gap-2 px-4 py-1.5 bg-amber-50 border-b border-amber-200 text-amber-700 text-xs shrink-0"
    >
      <svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 3a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4zm0 7.5a.875.875 0 1 1 0-1.75.875.875 0 0 1 0 1.75z" />
      </svg>
      Real-time updates unavailable — responses will still appear when complete.
    </div>
  </Transition>
</template>

<script setup>
defineProps({
  show: { type: Boolean, default: false },
});
</script>
