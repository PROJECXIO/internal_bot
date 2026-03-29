<template>
  <div class="flex" :class="isUser ? 'justify-end' : 'justify-start'">
    <!-- Agent avatar -->
    <div
      v-if="!isUser"
      class="w-7 h-7 flex items-center justify-center mr-2 mt-1 shrink-0"
    >
      <RevenyuCut class="w-5 h-5" />
    </div>

    <div
      class="max-w-[80%] rounded-2xl px-4 py-2.5 text-sm"
      :class="
        isUser
          ? 'bg-brand text-white rounded-br-sm'
          : 'bg-brand-light text-gray-900 rounded-bl-sm'
      "
    >
      <!-- User message -->
      <template v-if="isUser">
        <p class="whitespace-pre-wrap break-words">{{ message.content }}</p>
      </template>

      <!-- Bot: table result -->
      <template v-else-if="message.status === 'success' && message.rows && message.rows.length">
        <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-gray-500 mb-2">
          {{ message.title }}
        </p>
        <div class="overflow-x-auto rounded-lg border border-gray-200">
          <table class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th
                  v-for="col in message.columns"
                  :key="col"
                  class="bg-gray-50 px-3 py-1.5 text-left font-semibold text-gray-700 border-b border-gray-200 whitespace-nowrap"
                >{{ col }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in message.rows" :key="ri">
                <td
                  v-for="col in message.columns"
                  :key="col"
                  class="px-3 py-1.5 border-b border-gray-100 text-gray-600 last:border-0"
                >{{ row[col] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-xs text-gray-400 mt-1 text-right">
          {{ message.rows.length }} row{{ message.rows.length !== 1 ? 's' : '' }}
        </p>
      </template>

      <!-- Bot: empty success -->
      <template v-else-if="message.status === 'success'">
        <span class="italic text-gray-400">No results found.</span>
      </template>

      <!-- Bot: clarification needed -->
      <template v-else-if="message.status === 'clarification_needed'">
        <p class="break-words">{{ message.question }}</p>
        <div v-if="message.options && message.options.length" class="flex flex-wrap gap-2 mt-2">
          <button
            v-for="opt in message.options"
            :key="opt"
            class="bg-white border border-brand text-brand px-3 py-1 rounded-full text-xs hover:bg-brand-light transition-colors cursor-pointer"
            @click="$emit('option', opt)"
          >{{ opt }}</button>
        </div>
      </template>

      <!-- Bot: blocked -->
      <template v-else-if="message.status === 'blocked'">
        <span class="text-yellow-600">🔒 {{ message.reason }}</span>
      </template>

      <!-- Bot: error -->
      <template v-else-if="message.status === 'error'">
        <span class="text-red-500">⚠️ {{ message.reason }}</span>
      </template>

      <!-- Bot: plain text / markdown -->
      <template v-else>
        <div
          class="prose-chat break-words"
          v-html="renderMarkdown(message.content || '')"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { marked } from "marked";
import RevenyuCut from "./RevenyuCut.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

defineEmits(["option"]);

const isUser = computed(() => props.message.role === "user");

function renderMarkdown(text) {
  return marked.parse(text, { async: false });
}
</script>
