<template>
  <div
    class="flex min-w-0"
    :class="[isUser ? 'justify-end' : 'justify-start', isInlineChartExpanded && !isUser ? 'w-full' : '']"
  >
    <!-- Agent avatar -->
    <div
      v-if="!isUser"
      class="w-7 h-7 flex items-center justify-center mr-2 mt-1 shrink-0"
    >
      <RevenyuCut class="w-5 h-5" />
    </div>

    <div
      class="rounded-2xl px-4 py-2.5 text-sm transition-[max-width] duration-200"
      :style="bubbleStyle"
      :class="
        isUser
          ? 'bg-brand text-white rounded-br-sm'
          : isInlineChartExpanded
            ? 'bg-brand-light text-gray-900 rounded-bl-sm'
            : 'bg-brand-light text-gray-900 rounded-bl-sm max-w-[80%]'
      "
    >
      <!-- User message -->
      <template v-if="isUser">
        <p class="whitespace-pre-wrap break-words">{{ message.content }}</p>
      </template>

      <template v-else-if="message.status === 'success' && message.responseType === 'plain_text'">
        <div class="space-y-3">
          <div>
            <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
              {{ message.answerPrefix }}
            </p>
            <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-slate-500 mb-1">
              {{ message.title }}
            </p>
            <div
              v-if="message.markdown"
              class="prose-chat prose-chat--structured break-words text-slate-800"
              v-html="renderMarkdown(message.markdown)"
            />
            <p v-else class="whitespace-pre-wrap break-words text-slate-800">
              {{ message.summary || message.content }}
            </p>
          </div>

          <div v-if="message.rows && message.rows.length" class="flex items-center gap-3">
            <button
              class="text-xs font-medium text-brand hover:text-brand-dark transition-colors cursor-pointer"
              @click="showTable = !showTable"
            >
              {{ showTable ? "Hide data" : "Show data" }}
            </button>
            <button
              type="button"
              class="message-action-icon-button"
              title="Export CSV"
              aria-label="Export CSV"
              @click="exportCSV"
            >
              <span class="message-action-icon" aria-hidden="true" v-html="exportIconSvg" />
            </button>
          </div>

          <div v-if="message.rows && message.rows.length && showTable" class="space-y-2">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Raw data</p>
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
                      class="bg-white px-3 py-1.5 border-b border-gray-100 text-gray-600 last:border-0"
                    >{{ row[col] ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="message.status === 'success' && message.responseType === 'metric_card' && message.visualization">
        <div class="metric-card">
          <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
            {{ message.answerPrefix }}
          </p>
          <div
            v-if="message.markdown"
            class="prose-chat prose-chat--structured structured-response-copy break-words"
            v-html="renderMarkdown(message.markdown)"
          />
          <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-slate-500">
            {{ message.title }}
          </p>
          <p class="metric-card__label">
            {{ message.visualization.label }}
          </p>
          <p class="metric-card__value">
            {{ message.visualization.formatted_value }}
          </p>
          <p v-if="message.visualization.context" class="metric-card__context">
            {{ message.visualization.context }}
          </p>
          <p v-if="message.summary && !message.markdown" class="metric-card__summary">
            {{ message.summary }}
          </p>
        </div>
      </template>

      <template
        v-else-if="message.status === 'success' && isChartResponse && message.visualization"
      >
        <div class="space-y-3">
          <div>
            <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
              {{ message.answerPrefix }}
            </p>
            <div
              v-if="message.markdown"
              class="prose-chat prose-chat--structured structured-response-copy break-words"
              v-html="renderMarkdown(message.markdown)"
            />
            <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-slate-500 mb-1">
              {{ message.title }}
            </p>
            <p v-if="message.summary && !message.markdown" class="text-sm text-slate-700">
              {{ message.summary }}
            </p>
          </div>

          <div
            class="chart-card transition-all duration-200"
            :class="isInlineChartExpanded ? 'chart-card--expanded' : ''"
          >
            <VueApexCharts
              :type="chartType"
              :height="inlineChartHeight"
              :options="inlineChartOptions"
              :series="chartSeries"
            />
          </div>

          <!-- Chart legend for highest/lowest -->
          <div v-if="chartType === 'bar' && chartHighLow" class="flex gap-3 text-[10px] text-slate-500">
            <span class="flex items-center gap-1">
              <span class="inline-block w-2.5 h-2.5 rounded-sm" style="background:#0f766e"></span> Highest
            </span>
            <span class="flex items-center gap-1">
              <span class="inline-block w-2.5 h-2.5 rounded-sm" style="background:#f59e0b"></span> Lowest
            </span>
          </div>

          <div class="flex items-center gap-3">
            <button
              type="button"
              class="message-action-icon-button"
              :title="isInlineChartExpanded ? 'Collapse chart' : 'Expand chart'"
              :aria-label="isInlineChartExpanded ? 'Collapse chart' : 'Expand chart'"
              @click="toggleInlineExpand"
            >
              <span class="message-action-icon" aria-hidden="true" v-html="expandIconSvg" />
            </button>
            <button
              type="button"
              class="message-action-icon-button"
              title="Open fullscreen"
              aria-label="Open fullscreen"
              @click="openChartDialog"
            >
              <span class="message-action-icon" aria-hidden="true" v-html="fullscreenIconSvg" />
            </button>
            <button
              v-if="message.visualization.show_table_toggle"
              class="text-xs font-medium text-brand hover:text-brand-dark transition-colors cursor-pointer"
              @click="showTable = !showTable"
            >
              {{ showTable ? "Hide data" : "Show data" }}
            </button>
            <button
              v-if="message.columns && message.rows && message.rows.length"
              type="button"
              class="message-action-icon-button"
              title="Export CSV"
              aria-label="Export CSV"
              @click="exportCSV"
            >
              <span class="message-action-icon" aria-hidden="true" v-html="exportIconSvg" />
            </button>
          </div>

          <div v-if="showTable" class="space-y-2">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Raw data</p>
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
                      class="bg-white px-3 py-1.5 border-b border-gray-100 text-gray-600 last:border-0"
                    >{{ row[col] ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <Teleport to="body">
            <div
              v-if="isChartDialogOpen"
              class="chart-dialog-backdrop"
              @click.self="closeChartDialog"
            >
              <div class="chart-dialog">
                <div class="chart-dialog__header">
                  <div class="chart-dialog__heading">
                    <p v-if="message.title" class="chart-dialog__eyebrow">{{ message.title }}</p>
                    <p class="chart-dialog__title">
                      {{ message.answerPrefix || message.summary || "Chart details" }}
                    </p>
                  </div>

                  <div class="chart-dialog__actions">
                    <button
                      v-if="message.columns && message.rows && message.rows.length"
                      type="button"
                      class="message-action-icon-button"
                      title="Export CSV"
                      aria-label="Export CSV"
                      @click="exportCSV"
                    >
                      <span class="message-action-icon" aria-hidden="true" v-html="exportIconSvg" />
                    </button>
                    <button
                      type="button"
                      class="message-action-icon-button"
                      title="Close chart"
                      aria-label="Close chart"
                      @click="closeChartDialog"
                    >
                      <span class="message-action-icon" aria-hidden="true" v-html="closeIconSvg" />
                    </button>
                  </div>
                </div>

                <div class="chart-dialog__body">
                  <VueApexCharts
                    :type="chartType"
                    height="420"
                    :options="expandedChartOptions"
                    :series="chartSeries"
                  />
                </div>
              </div>
            </div>
          </Teleport>
        </div>
      </template>

      <template v-else-if="message.status === 'success' && message.rows && message.rows.length">
        <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
          {{ message.answerPrefix }}
        </p>
        <div
          v-if="message.markdown"
          class="prose-chat prose-chat--structured structured-response-copy break-words"
          v-html="renderMarkdown(message.markdown)"
        />
        <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-gray-500 mb-2">
          {{ message.title }}
        </p>
        <p v-if="message.summary && !message.markdown" class="text-sm text-slate-700 mb-2">
          {{ message.summary }}
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
                  class="bg-white px-3 py-1.5 border-b border-gray-100 text-gray-600 last:border-0"
                >{{ row[col] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex justify-between items-center mt-1">
          <p class="text-xs text-gray-400">
            {{ message.rows.length }} row{{ message.rows.length !== 1 ? 's' : '' }}
          </p>
          <button
            type="button"
            class="message-action-icon-button"
            title="Export CSV"
            aria-label="Export CSV"
            @click="exportCSV"
          >
            <span class="message-action-icon" aria-hidden="true" v-html="exportIconSvg" />
          </button>
        </div>
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

      <!-- Bot: greeting -->
      <template v-else-if="message.status === 'greeting'">
        <p class="whitespace-pre-wrap break-words">{{ message.content }}</p>
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

      <div v-if="showConfidence" class="answer-quality">
        <span class="answer-quality__dots" :title="`Confidence: ${Math.round(confidenceScore * 100)}%`">
          <span
            v-for="i in 5"
            :key="i"
            class="answer-quality__dot"
            :class="i <= confidenceDots ? 'answer-quality__dot--filled' : 'answer-quality__dot--empty'"
          >●</span>
        </span>
        <span class="answer-quality__label">{{ confidenceLabelText }}</span>
      </div>

      <details v-if="hasDebugPanel" class="message-debug-panel">
        <summary class="message-debug-panel__summary">
          <span>Debug context</span>
          <span v-if="debugTokenUsage.total_tokens" class="message-debug-panel__token-pill">
            {{ debugTokenUsage.total_tokens.toLocaleString() }} tokens
          </span>
        </summary>

        <div class="message-debug-panel__body">
          <div v-if="debugTokenUsage.total_tokens" class="message-debug-panel__metrics">
            <div class="message-debug-panel__metric">
              <span class="message-debug-panel__metric-label">Input</span>
              <span class="message-debug-panel__metric-value">{{ debugTokenUsage.input_tokens.toLocaleString() }}</span>
            </div>
            <div class="message-debug-panel__metric">
              <span class="message-debug-panel__metric-label">Output</span>
              <span class="message-debug-panel__metric-value">{{ debugTokenUsage.output_tokens.toLocaleString() }}</span>
            </div>
            <div class="message-debug-panel__metric">
              <span class="message-debug-panel__metric-label">Total</span>
              <span class="message-debug-panel__metric-value">{{ debugTokenUsage.total_tokens.toLocaleString() }}</span>
            </div>
          </div>

          <div v-if="debugQuestionContextEntries.length" class="message-debug-panel__section">
            <p class="message-debug-panel__label">Question context</p>
            <div class="message-debug-panel__kv-grid">
              <div
                v-for="entry in debugQuestionContextEntries"
                :key="entry.key"
                class="message-debug-panel__kv-item"
              >
                <span class="message-debug-panel__kv-key">{{ entry.label }}</span>
                <span class="message-debug-panel__kv-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>

          <div
            v-for="section in debugTextSections"
            :key="section.key"
            class="message-debug-panel__section"
          >
            <p class="message-debug-panel__label">{{ section.label }}</p>
            <pre class="message-debug-panel__pre">{{ section.content }}</pre>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { marked } from "marked";
import VueApexCharts from "vue3-apexcharts";
import RevenyuCut from "./RevenyuCut.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

defineEmits(["option"]);

const isUser = computed(() => props.message.role === "user");
const showTable = ref(false);
const isInlineChartExpanded = ref(false);
const isChartDialogOpen = ref(false);

const downloadIconSvg = `
  <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M10 3.75v7.5m0 0 3-3m-3 3-3-3M4.75 13.75v1.5c0 .69.56 1.25 1.25 1.25h8c.69 0 1.25-.56 1.25-1.25v-1.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" />
  </svg>
`.trim();

const exportIconSvg = `
  <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M12 4.5h2.25A1.75 1.75 0 0 1 16 6.25v7.5a1.75 1.75 0 0 1-1.75 1.75h-8.5A1.75 1.75 0 0 1 4 13.75v-7.5A1.75 1.75 0 0 1 5.75 4.5H8m2-1.75V10m0 0 2.5-2.5M10 10 7.5 7.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" />
  </svg>
`.trim();

const expandIconSvg = `
  <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M7 4.75H4.75V7M13 4.75h2.25V7M7 15.25H4.75V13M13 15.25h2.25V13M5 5l3.25 3.25M15 5l-3.25 3.25M5 15l3.25-3.25M15 15l-3.25-3.25" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.55" />
  </svg>
`.trim();

const fullscreenIconSvg = `
  <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M3.75 7V3.75H7M16.25 7V3.75H13M3.75 13v3.25H7M16.25 13v3.25H13" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" />
  </svg>
`.trim();

const closeIconSvg = `
  <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M6 6l8 8M14 6l-8 8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" />
  </svg>
`.trim();

const isChartResponse = computed(() =>
  ["bar_chart", "pie_chart", "line_chart"].includes(props.message.responseType)
);

const bubbleStyle = computed(() => {
  if (!isInlineChartExpanded.value || isUser.value) return null;
  return {
    width: "min(1120px, calc(100% - 2.25rem))",
    maxWidth: "calc(100% - 2.25rem)",
  };
});

const inlineChartHeight = computed(() => (isInlineChartExpanded.value ? 420 : 260));

const chartType = computed(() => {
  const kind = props.message.visualization?.kind;
  if (kind === "pie") return "pie";
  if (kind === "line") return "line";
  return "bar";
});

const confidenceScore = computed(() => props.message.meta?.confidence ?? null);
const confidenceLabel = computed(() => props.message.meta?.confidence_label || "");
const confidenceDots = computed(() => {
  const score = confidenceScore.value;
  if (score === null) return 0;
  if (score >= 0.85) return 5;
  if (score >= 0.70) return 4;
  if (score >= 0.55) return 3;
  if (score >= 0.35) return 2;
  return 1;
});
const showConfidence = computed(() =>
  !isUser.value && props.message.status === "success" && confidenceScore.value !== null
);
const confidenceLabelText = computed(() => {
  const labels = { high: "Strong", medium: "Moderate", low: "Weak", very_low: "Uncertain" };
  return labels[confidenceLabel.value] || "";
});

const hasDebugPanel = computed(() => {
  const debug = props.message.debug;
  return Boolean(
    !isUser.value
    && debug
    && (
      debug.context_window
      || (debug.token_usage && (debug.token_usage.input_tokens || debug.token_usage.output_tokens))
    )
  );
});

const debugTokenUsage = computed(() => {
  const tokenUsage = props.message.debug?.token_usage || {};
  const inputTokens = Number(tokenUsage.input_tokens || 0);
  const outputTokens = Number(tokenUsage.output_tokens || 0);
  return {
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: Number(tokenUsage.total_tokens || inputTokens + outputTokens),
  };
});

const debugQuestionContextEntries = computed(() => {
  const questionContext = props.message.debug?.context_window?.question_context || {};
  return [
    { key: "raw_message", label: "Raw message", value: questionContext.raw_message },
    { key: "normalized_question", label: "Normalized question", value: questionContext.normalized_question },
    { key: "follow_up", label: "Follow-up reuse", value: formatDebugQuestionValue(questionContext.follow_up_to_previous_result) },
    { key: "last_user_question", label: "Last user question", value: questionContext.last_user_question },
    { key: "last_non_follow_up_user_question", label: "Last non-follow-up question", value: questionContext.last_non_follow_up_user_question },
    { key: "discovered_doctypes", label: "Discovered DocTypes", value: formatDebugQuestionValue(questionContext.discovered_doctypes) },
    { key: "visualization_preference", label: "Visualization preference", value: questionContext.visualization_preference },
  ].filter((entry) => entry.value !== "");
});

const debugTextSections = computed(() => {
  const contextWindow = props.message.debug?.context_window || {};
  return [
    { key: "history", label: "History", content: formatDebugHistory(contextWindow.history) },
    { key: "memory_summary", label: "Memory summary", content: formatDebugBlock(contextWindow.memory_summary) },
    { key: "last_result_context", label: "Last result context", content: formatDebugBlock(contextWindow.last_result_context) },
    { key: "schema_context", label: "Schema context", content: formatDebugBlock(contextWindow.schema_context) },
  ].filter((section) => section.content);
});

const chartSeries = computed(() => {
  const visualization = props.message.visualization;
  if (!visualization) return [];

  if (visualization.kind === "pie") {
    return visualization.series || [];
  }

  return visualization.series?.map((series) => ({
    ...series,
    data: series.data || [],
  })) || [];
});

// Compute highest/lowest indices for bar charts
const chartHighLow = computed(() => {
  const visualization = props.message.visualization;
  if (!visualization || visualization.kind === "pie" || visualization.kind === "grouped_bar") return null;

  const data = visualization.series?.[0]?.data || [];
  if (data.length < 2) return null;

  let maxIdx = 0, minIdx = 0;
  for (let i = 1; i < data.length; i++) {
    if (data[i] > data[maxIdx]) maxIdx = i;
    if (data[i] < data[minIdx]) minIdx = i;
  }
  // Don't highlight if all values are equal
  if (data[maxIdx] === data[minIdx]) return null;

  return { maxIdx, minIdx, maxVal: data[maxIdx], minVal: data[minIdx] };
});

function buildChartOptions(expanded = false) {
  const visualization = props.message.visualization;
  const categories = visualization?.categories || [];
  const valueLabel = visualization?.value_key?.replaceAll("_", " ")
    || (visualization?.kind === "grouped_bar" ? "Metrics" : "Value");
  const isGroupedBar = visualization?.kind === "grouped_bar";
  const isHorizontal = visualization?.layout === "horizontal";

  if (visualization?.kind === "pie") {
    return {
      chart: {
        toolbar: {
          show: true,
          tools: { download: downloadIconSvg, selection: false, zoom: false, zoomin: false, zoomout: false, pan: false, reset: false },
        },
      },
      labels: categories,
      legend: {
        position: "bottom",
        fontSize: expanded ? "13px" : "12px",
      },
      stroke: {
        colors: ["#ffffff"],
      },
      dataLabels: {
        enabled: true,
      },
      colors: ["#0f766e", "#14b8a6", "#5eead4", "#99f6e4", "#134e4a", "#2dd4bf"],
      tooltip: {
        y: {
          formatter: (value) => formatChartValue(value),
        },
      },
    };
  }

  if (visualization?.kind === "line") {
    return {
      chart: {
        toolbar: {
          show: true,
          tools: { download: downloadIconSvg, selection: false, zoom: false, zoomin: false, zoomout: false, pan: false, reset: false },
        },
      },
      stroke: { curve: "smooth", width: 3 },
      markers: { size: 4, hover: { sizeOffset: 2 } },
      dataLabels: { enabled: false },
      xaxis: {
        categories,
        labels: {
          rotate: expanded ? -12 : -20,
          style: { fontSize: expanded ? "12px" : "11px" },
        },
      },
      yaxis: {
        title: { text: valueLabel },
        labels: { formatter: (value) => formatChartValue(value) },
      },
      legend: { show: false },
      colors: ["#0f766e"],
      tooltip: {
        y: { formatter: (value) => formatChartValue(value) },
      },
    };
  }

  if (isGroupedBar) {
    return {
      chart: {
        toolbar: {
          show: true,
          tools: { download: downloadIconSvg, selection: false, zoom: false, zoomin: false, zoomout: false, pan: false, reset: false },
        },
        stacked: false,
      },
      plotOptions: {
        bar: {
          horizontal: isHorizontal,
          borderRadius: 5,
          columnWidth: isHorizontal ? undefined : "56%",
          barHeight: isHorizontal ? "58%" : undefined,
          distributed: false,
        },
      },
      dataLabels: {
        enabled: false,
      },
      xaxis: {
        categories,
        labels: {
          rotate: isHorizontal ? 0 : expanded ? -12 : -20,
          style: {
            fontSize: expanded ? "12px" : "11px",
          },
        },
      },
      yaxis: {
        title: {
          text: valueLabel,
        },
        labels: {
          formatter: (value) => formatChartValue(value),
        },
      },
      legend: {
        show: true,
        position: "bottom",
        fontSize: expanded ? "13px" : "12px",
      },
      colors: ["#0f766e", "#14b8a6", "#5eead4", "#99f6e4", "#134e4a", "#2dd4bf"],
      tooltip: {
        shared: true,
        intersect: false,
        y: {
          formatter: (value) => formatChartValue(value),
        },
      },
    };
  }

  // Bar chart colors — highlight highest (dark teal) and lowest (amber)
  const data = visualization?.series?.[0]?.data || [];
  const hl = chartHighLow.value;
  const barColors = data.map((_, i) => {
    if (hl && i === hl.maxIdx) return "#0f766e";
    if (hl && i === hl.minIdx) return "#f59e0b";
    return "#5eead4";
  });

  // Annotations for highest/lowest labels
  const annotations = { points: [] };
  if (hl && categories.length) {
    annotations.points.push({
      x: categories[hl.maxIdx],
      y: hl.maxVal,
      marker: { size: 0 },
      label: {
        text: `${formatChartValue(hl.maxVal)}`,
        borderColor: "#0f766e",
        style: { background: "#0f766e", color: "#fff", fontSize: "10px", padding: { left: 6, right: 6, top: 2, bottom: 2 } },
        offsetY: -8,
      },
    });
    annotations.points.push({
      x: categories[hl.minIdx],
      y: hl.minVal,
      marker: { size: 0 },
      label: {
        text: `${formatChartValue(hl.minVal)}`,
        borderColor: "#f59e0b",
        style: { background: "#f59e0b", color: "#fff", fontSize: "10px", padding: { left: 6, right: 6, top: 2, bottom: 2 } },
        offsetY: -8,
      },
    });
  }

  return {
    chart: {
      toolbar: {
        show: true,
        tools: { download: downloadIconSvg, selection: false, zoom: false, zoomin: false, zoomout: false, pan: false, reset: false },
      },
      sparkline: { enabled: false },
    },
    plotOptions: {
      bar: {
        borderRadius: 6,
        distributed: true,
        columnWidth: "48%",
      },
    },
    annotations,
    dataLabels: {
      enabled: false,
    },
    xaxis: {
      categories,
      labels: {
        rotate: expanded ? -12 : -20,
        style: {
          fontSize: expanded ? "12px" : "11px",
        },
      },
    },
    yaxis: {
      title: {
        text: valueLabel,
      },
      labels: {
        formatter: (value) => formatChartValue(value),
      },
    },
    legend: {
      show: false,
    },
    colors: barColors.length ? barColors : ["#0f766e", "#14b8a6", "#5eead4", "#99f6e4", "#134e4a", "#2dd4bf"],
    tooltip: {
      y: {
        formatter: (value) => formatChartValue(value),
      },
    },
  };
}

const chartOptions = computed(() => buildChartOptions(false));
const inlineChartOptions = computed(() => buildChartOptions(isInlineChartExpanded.value));
const expandedChartOptions = computed(() => buildChartOptions(true));

function renderMarkdown(text) {
  return marked.parse(text, { async: false });
}

function formatDebugHistory(history) {
  if (!Array.isArray(history) || !history.length) return "";
  return history
    .map((entry) => `${String(entry.role || "").toUpperCase()}: ${entry.content || ""}`.trim())
    .join("\n\n");
}

function formatDebugBlock(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value) || typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value).trim();
}

function formatDebugQuestionValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value).trim();
}

function formatChartValue(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return new Intl.NumberFormat().format(number);
}

function exportCSV() {
  const cols = props.message.columns;
  const rows = props.message.rows;
  if (!cols?.length || !rows?.length) return;

  const escapeCsv = (val) => {
    const str = String(val ?? "");
    return str.includes(",") || str.includes('"') || str.includes("\n")
      ? `"${str.replace(/"/g, '""')}"`
      : str;
  };

  const header = cols.map(escapeCsv).join(",");
  const body = rows
    .map((row) => cols.map((c) => escapeCsv(row[c])).join(","))
    .join("\n");

  const blob = new Blob([header + "\n" + body], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (props.message.title || "data").replace(/[^a-zA-Z0-9 ]/g, "") + ".csv";
  a.click();
  URL.revokeObjectURL(url);
}

function openChartDialog() {
  isChartDialogOpen.value = true;
}

function closeChartDialog() {
  isChartDialogOpen.value = false;
}

function toggleInlineExpand() {
  isInlineChartExpanded.value = !isInlineChartExpanded.value;
}

function handleKeydown(event) {
  if (event.key === "Escape" && isChartDialogOpen.value) {
    closeChartDialog();
  }
}

onMounted(() => {
  document.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleKeydown);
});
</script>
