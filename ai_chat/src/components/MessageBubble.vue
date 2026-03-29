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
        <p class="whitespace-pre-wrap break-words text-slate-800">
          {{ message.summary || message.content }}
        </p>
      </template>

      <template v-else-if="message.status === 'success' && message.responseType === 'metric_card' && message.visualization">
        <div class="metric-card">
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

          <button
            v-if="message.visualization.show_table_toggle"
            class="text-xs font-medium text-brand hover:text-brand-dark transition-colors cursor-pointer"
            @click="showTable = !showTable"
          >
            {{ showTable ? "Hide data" : "Show data" }}
          </button>

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

const chartOptions = computed(() => {
  const visualization = props.message.visualization;
  const categories = visualization?.categories || [];
  const valueLabel = visualization?.value_key?.replaceAll("_", " ") || "Value";

  if (visualization?.kind === "pie") {
    return {
      chart: {
        toolbar: { show: false },
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

  return {
    chart: {
      toolbar: { show: false },
      sparkline: { enabled: false },
    },
    plotOptions: {
      bar: {
        borderRadius: 6,
        distributed: true,
        columnWidth: "48%",
      },
    },
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
    colors: ["#0f766e", "#14b8a6", "#5eead4", "#99f6e4", "#134e4a", "#2dd4bf"],
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
</script>
