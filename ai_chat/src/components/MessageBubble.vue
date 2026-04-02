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

      <template v-else-if="message.status === 'success' && message.responseType === 'plain_text'">
        <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
          {{ message.answerPrefix }}
        </p>
        <p class="whitespace-pre-wrap break-words text-slate-800">
          {{ message.summary || message.content }}
        </p>
      </template>

      <template v-else-if="message.status === 'success' && message.responseType === 'metric_card' && message.visualization">
        <div class="metric-card">
          <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
            {{ message.answerPrefix }}
          </p>
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
          <p v-if="message.summary" class="metric-card__summary">
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
            <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-slate-500 mb-1">
              {{ message.title }}
            </p>
            <p v-if="message.summary" class="text-sm text-slate-700">
              {{ message.summary }}
            </p>
          </div>

          <div class="chart-card">
            <VueApexCharts
              :type="chartType"
              height="260"
              :options="chartOptions"
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
        </div>
      </template>

      <template v-else-if="message.status === 'success' && message.rows && message.rows.length">
        <p v-if="message.answerPrefix" class="text-sm font-medium text-slate-600 mb-1">
          {{ message.answerPrefix }}
        </p>
        <p v-if="message.title" class="font-semibold text-xs uppercase tracking-wide text-gray-500 mb-2">
          {{ message.title }}
        </p>
        <p v-if="message.summary" class="text-sm text-slate-700 mb-2">
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
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { marked } from "marked";
import VueApexCharts from "vue3-apexcharts";
import RevenyuCut from "./RevenyuCut.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

defineEmits(["option"]);

const isUser = computed(() => props.message.role === "user");
const showTable = ref(false);

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

const isChartResponse = computed(() =>
  ["bar_chart", "pie_chart"].includes(props.message.responseType)
);

const chartType = computed(() =>
  props.message.visualization?.kind === "pie" ? "pie" : "bar"
);

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
  if (!visualization || visualization.kind === "pie") return null;

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

const chartOptions = computed(() => {
  const visualization = props.message.visualization;
  const categories = visualization?.categories || [];
  const valueLabel = visualization?.value_key?.replaceAll("_", " ") || "Value";

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
        fontSize: "12px",
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
        rotate: -20,
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
});

function renderMarkdown(text) {
  return marked.parse(text, { async: false });
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
</script>
