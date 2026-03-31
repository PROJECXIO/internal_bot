<template>
  <div class="flex justify-start">
    <!-- Avatar -->
    <div class="w-7 h-7 flex items-center justify-center mr-2 mt-1 shrink-0">
      <RevenyuCut class="w-5 h-5" />
    </div>

    <!-- Bubble -->
    <div class="bg-brand-light rounded-2xl rounded-bl-sm px-4 py-3 min-w-[160px]">
      <!-- Step list when we have events -->
      <TransitionGroup
        v-if="steps.length > 0"
        tag="ul"
        name="step"
        class="flex flex-col gap-1.5 list-none m-0 p-0"
      >
        <li
          v-for="step in steps"
          :key="step.node + step.attempt"
          class="flex items-center gap-2"
        >
          <!-- Status icon -->
          <span v-if="step.status === 'done'" class="progress-step-done-dot shrink-0">
            <!-- checkmark -->
            <svg class="w-3 h-3 text-brand" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="5.5" fill="currentColor" fill-opacity="0.15" stroke="currentColor" />
              <path d="M3.5 6l1.8 1.8 3.2-3.2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span v-else class="progress-step-active-dot shrink-0">
            <!-- pulsing ring -->
            <svg class="w-3 h-3 text-brand" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="4" fill="currentColor" />
            </svg>
          </span>

          <!-- Label -->
          <span
            class="text-xs leading-none"
            :class="step.status === 'done' ? 'text-slate-400' : 'text-slate-700 font-medium'"
          >
            {{ step.label }}<span v-if="step.status === 'active'" class="progress-ellipsis" />
          </span>
        </li>
      </TransitionGroup>

      <!-- Fallback bouncing dots when no events received yet -->
      <div v-else class="flex gap-1 items-center">
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 0ms" />
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 150ms" />
        <span class="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style="animation-delay: 300ms" />
      </div>
    </div>
  </div>
</template>

<script setup>
import RevenyuCut from "./RevenyuCut.vue";

defineProps({
  steps: { type: Array, default: () => [] },
  // Each step: { node: String, label: String, status: 'active'|'done', attempt: Number }
});
</script>
