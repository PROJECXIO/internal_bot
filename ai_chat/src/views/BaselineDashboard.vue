<template>
  <div class="baseline-root">
    <!-- Header -->
    <header class="baseline-header">
      <div class="baseline-header__left">
        <router-link to="/" class="baseline-back" aria-label="Back to chat">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </router-link>
        <h1 class="baseline-header__title">Baseline Dashboard</h1>
      </div>

      <div class="baseline-header__controls">
        <select v-model="selectedFixture" class="baseline-select" :disabled="running">
          <option value="baseline_queries.json">baseline_queries.json</option>
          <option value="golden_queries.json">golden_queries.json</option>
        </select>
        <button class="baseline-btn baseline-btn--primary" :disabled="running" @click="startRun">
          <span v-if="running" class="baseline-spinner" aria-hidden="true" />
          {{ running ? 'Running…' : 'Run Baseline' }}
        </button>
      </div>
    </header>

    <!-- Global error -->
    <div v-if="globalError" class="baseline-error" role="alert">{{ globalError }}</div>

    <!-- Progress bar (during active run) -->
    <div v-if="running" class="baseline-progress-bar-wrap" aria-live="polite">
      <div class="baseline-progress-bar" :style="{ width: progressPct + '%' }" />
      <span class="baseline-progress-label">
        <span class="baseline-live-dot" />
        {{ activeRunStatus.completed_queries || 0 }} / {{ activeRunStatus.total_queries || '?' }}
      </span>
    </div>

    <div class="baseline-body">
      <!-- Run history sidebar -->
      <aside class="baseline-history">
        <p class="baseline-history__label">Run history</p>
        <div
          v-for="run in runs"
          :key="run.name"
          class="baseline-history__item"
          :class="{ 'baseline-history__item--active': selectedRunId === run.name }"
          @click="selectRun(run.name)"
        >
          <div class="baseline-history__item-fixture">{{ run.fixture_name }}</div>
          <div class="baseline-history__item-meta">
            <span class="baseline-status-badge" :class="statusClass(run.status)">{{ run.status }}</span>
            <span class="baseline-history__item-date">{{ formatDate(run.creation) }}</span>
          </div>
          <div v-if="run.status === 'Completed'" class="baseline-history__item-counts">
            {{ run.success_count }}✓ {{ run.error_count }}✗ {{ run.status_mismatch_count }} mis
          </div>
        </div>
        <p v-if="!runs.length && !loadingRuns" class="baseline-history__empty">No runs yet.</p>
      </aside>

      <!-- Main content -->
      <main class="baseline-main" v-if="currentRun">

        <!-- KPI zones -->
        <section class="baseline-section">

          <!-- Zone 1: Run Overview -->
          <div class="kpi-zone">
            <p class="kpi-zone__header">Run Overview</p>

            <!-- Primary row: featured + top 3 -->
            <div class="kpi-row kpi-row--primary" :key="selectedRunId + 'p'">
              <div class="kpi kpi--featured">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                <div class="kpi__label">Total Queries</div>
                <div class="kpi__value">{{ sv('total_queries') }}</div>
                <div class="kpi__bar">
                  <div class="kpi__bar-fill" :style="{ width: passRatePct + '%' }" />
                </div>
                <div class="kpi__sub">{{ passRatePct }}% pass rate</div>
              </div>
              <div class="kpi kpi--success">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                <div class="kpi__label">Success</div>
                <div class="kpi__value">{{ sv('success_count') }}</div>
              </div>
              <div class="kpi kpi--error">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                <div class="kpi__label">Errors</div>
                <div class="kpi__value">{{ sv('error_count') }}</div>
              </div>
              <div class="kpi kpi--mismatch">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                <div class="kpi__label">Mismatches</div>
                <div class="kpi__value">{{ (currentSummary && currentSummary.status_mismatches && currentSummary.status_mismatches.length) || 0 }}</div>
              </div>
            </div>

            <!-- Secondary row: compact stats -->
            <div class="kpi-row kpi-row--secondary" :key="selectedRunId + 's'">
              <div class="kpi kpi--warn kpi--compact">
                <div class="kpi__label">Clarification</div>
                <div class="kpi__value">{{ sv('clarification_count') }}</div>
              </div>
              <div class="kpi kpi--slate kpi--compact">
                <div class="kpi__label">Blocked</div>
                <div class="kpi__value">{{ sv('blocked_count') }}</div>
              </div>
              <div class="kpi kpi--slate kpi--compact">
                <div class="kpi__label">Greeting</div>
                <div class="kpi__value">{{ sv('greeting_count') }}</div>
              </div>
              <div class="kpi kpi--slate kpi--compact">
                <div class="kpi__label">No Rows</div>
                <div class="kpi__value">{{ (currentSummary && currentSummary.queries_with_no_rows && currentSummary.queries_with_no_rows.length) || 0 }}</div>
              </div>
              <div class="kpi kpi--blue kpi--compact">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <div class="kpi__label">Avg Time</div>
                <div class="kpi__value">{{ avgTimingDisplay }}</div>
              </div>
              <div class="kpi kpi--slate kpi--compact">
                <svg class="kpi__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <div class="kpi__label">Avg Retries</div>
                <div class="kpi__value">{{ sv('average_retries') }}</div>
              </div>
            </div>
          </div>

          <!-- Zone 2: Cost & Usage (dark) -->
          <div v-if="tokensSummaryAvailable" class="kpi-zone kpi-zone--dark" :key="selectedRunId + 't'">
            <p class="kpi-zone__header">⚡ Cost &amp; Usage</p>
            <div class="kpi-zone__cards">
              <div class="kpi kpi--dark kpi--electric-blue">
                <div class="kpi__label"><span class="kpi__accent">↑</span>&nbsp;Input Tokens</div>
                <div class="kpi__value">{{ fmtNum(sv('total_input_tokens')) }}</div>
                <div class="kpi__sub">avg {{ sv('average_input_tokens') }} / query</div>
              </div>
              <div class="kpi kpi--dark kpi--violet">
                <div class="kpi__label"><span class="kpi__accent">↓</span>&nbsp;Output Tokens</div>
                <div class="kpi__value">{{ fmtNum(sv('total_output_tokens')) }}</div>
                <div class="kpi__sub">avg {{ sv('average_output_tokens') }} / query</div>
              </div>
              <div
                v-if="estimatedCost"
                class="kpi kpi--dark kpi--gold"
                :title="`Approx. based on ${estimatedCost.model} list pricing`"
              >
                <div class="kpi__label"><span class="kpi__accent">$</span>&nbsp;Est. Run Cost</div>
                <div class="kpi__value">~${{ estimatedCost.total.toFixed(4) }}</div>
                <div class="kpi__sub">{{ estimatedCost.model }}</div>
              </div>
            </div>
          </div>

        </section>

        <!-- Charts -->
        <section class="baseline-section baseline-charts-row">
          <!-- Status distribution -->
          <div class="baseline-chart-box">
            <h3 class="baseline-chart-box__title">Status Distribution</h3>
            <VueApexCharts v-if="statusDonutSeries.length" type="donut" :options="statusDonutOptions" :series="statusDonutSeries" />
            <p v-else class="baseline-chart-empty">No data</p>
          </div>

          <!-- Top failing categories -->
          <div class="baseline-chart-box">
            <h3 class="baseline-chart-box__title">Top Failing Categories</h3>
            <VueApexCharts v-if="failingCategories.length" type="bar" :options="failingBarOptions" :series="failingBarSeries" />
            <p v-else class="baseline-chart-empty">No failing categories</p>
          </div>
        </section>

        <!-- Timing & retries charts -->
        <section class="baseline-section baseline-charts-row" v-if="visibleResults.length">
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Wall Time by Query (ms)</h3>
            <VueApexCharts type="bar" :options="timingChartOptions" :series="timingChartSeries" />
          </div>
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Retries by Query</h3>
            <VueApexCharts type="bar" :options="retriesChartOptions" :series="retriesChartSeries" />
          </div>
        </section>

        <!-- Token usage charts -->
        <section class="baseline-section baseline-charts-row" v-if="tokensSummaryAvailable && visibleResults.length">
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Token Usage per Query (Input + Output)</h3>
            <VueApexCharts type="bar" :options="tokenPerQueryOptions" :series="tokenPerQuerySeries" />
          </div>
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Avg Tokens by Category</h3>
            <VueApexCharts v-if="tokenByCategoryData.length" type="bar" :options="tokenByCategoryOptions" :series="tokenByCategorySeries" />
            <p v-else class="baseline-chart-empty">No data</p>
          </div>
        </section>

        <!-- Query table -->
        <section class="baseline-section">
          <div class="baseline-table-controls">
            <input
              v-model="tableSearch"
              class="baseline-search"
              type="search"
              placeholder="Search id, message, category, status…"
              aria-label="Search queries"
            />
            <div class="baseline-filters" role="group" aria-label="Filter queries">
              <button
                v-for="f in filters"
                :key="f.key"
                class="baseline-filter-btn"
                :class="{ 'baseline-filter-btn--active': activeFilter === f.key }"
                @click="activeFilter = f.key"
              >{{ f.label }}</button>
            </div>
          </div>

          <div class="baseline-table-wrap">
            <table class="baseline-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Category</th>
                  <th>Lang</th>
                  <th>Expected</th>
                  <th>Actual</th>
                  <th>Rows</th>
                  <th>Retries</th>
                  <th>Time (ms)</th>
                  <th>Schema</th>
                  <th>In Tok</th>
                  <th>Out Tok</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in filteredResults"
                  :key="r.id"
                  class="baseline-table__row"
                  :class="{ 'baseline-table__row--mismatch': !r.status_matches_expected, 'baseline-table__row--seed': r.dependency_seed }"
                  @click="openDetail(r)"
                >
                  <td class="baseline-table__id">{{ r.id }}</td>
                  <td>{{ r.category }}</td>
                  <td>{{ r.language || 'en' }}</td>
                  <td><span class="baseline-status-badge" :class="statusClass(r.expected_status)">{{ r.expected_status }}</span></td>
                  <td><span class="baseline-status-badge" :class="statusClass(r.status)">{{ r.status }}</span></td>
                  <td>{{ r.returned_rows ?? '—' }}</td>
                  <td>{{ r.retries ?? 0 }}</td>
                  <td>{{ r.wall_time_ms != null ? Math.round(r.wall_time_ms) : '—' }}</td>
                  <td class="baseline-table__schema">{{ r.schema_decision || '—' }}</td>
                  <td class="baseline-table__tokens">{{ r.input_tokens || '—' }}</td>
                  <td class="baseline-table__tokens">{{ r.output_tokens || '—' }}</td>
                  <td class="baseline-table__cost">{{ perQueryCost(r) != null ? '~$' + perQueryCost(r).toFixed(5) : '—' }}</td>
                </tr>
                <tr v-if="!filteredResults.length">
                  <td colspan="12" class="baseline-table__empty">No matching queries.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </main>

      <main class="baseline-main baseline-main--empty" v-else-if="!loadingRuns">
        <p class="baseline-empty-state">No baseline run selected. Run a baseline to see results.</p>
      </main>
    </div>

    <!-- Detail drawer -->
    <transition name="drawer">
      <div v-if="detailRow" class="baseline-drawer" role="dialog" aria-modal="true" aria-label="Query detail">
        <div class="baseline-drawer__backdrop" @click="detailRow = null" />
        <div class="baseline-drawer__panel">
          <div class="baseline-drawer__header">
            <h2 class="baseline-drawer__title">{{ detailRow.id }} — {{ detailRow.category }}</h2>
            <button class="baseline-drawer__close" aria-label="Close" @click="detailRow = null">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="baseline-drawer__body">
            <!-- Key fields -->
            <div class="baseline-drawer__row">
              <span class="baseline-drawer__key">Message</span>
              <span class="baseline-drawer__val">{{ detailRow.message }}</span>
            </div>
            <div class="baseline-drawer__row" v-if="detailRow.normalized_question">
              <span class="baseline-drawer__key">Normalized</span>
              <span class="baseline-drawer__val">{{ detailRow.normalized_question }}</span>
            </div>
            <div class="baseline-drawer__row">
              <span class="baseline-drawer__key">Expected</span>
              <span class="baseline-status-badge" :class="statusClass(detailRow.expected_status)">{{ detailRow.expected_status }}</span>
            </div>
            <div class="baseline-drawer__row">
              <span class="baseline-drawer__key">Actual</span>
              <span class="baseline-status-badge" :class="statusClass(detailRow.status)">{{ detailRow.status }}</span>
            </div>
            <div class="baseline-drawer__row" v-if="detailRow.intent">
              <span class="baseline-drawer__key">Intent</span>
              <span class="baseline-drawer__val">{{ detailRow.intent }}</span>
            </div>
            <div class="baseline-drawer__row" v-if="detailRow.schema_decision">
              <span class="baseline-drawer__key">Schema Decision</span>
              <span class="baseline-drawer__val">{{ detailRow.schema_decision }}</span>
            </div>
            <div class="baseline-drawer__row" v-if="detailRow.discovered_doctypes && detailRow.discovered_doctypes.length">
              <span class="baseline-drawer__key">DocTypes</span>
              <span class="baseline-drawer__val">{{ (detailRow.discovered_doctypes || []).join(', ') }}</span>
            </div>
            <div class="baseline-drawer__row" v-if="detailRow.error_detail">
              <span class="baseline-drawer__key">Error</span>
              <span class="baseline-drawer__val baseline-drawer__val--error">{{ detailRow.error_detail }}</span>
            </div>

            <!-- Node trace waterfall -->
            <div v-if="detailRow.node_trace && detailRow.node_trace.length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Node Trace</h3>
              <div class="baseline-waterfall">
                <div
                  v-for="entry in nodeTimingWaterfall"
                  :key="entry.node"
                  class="baseline-waterfall__row"
                  :class="{ 'baseline-waterfall__row--longest': entry.isLongest }"
                >
                  <span class="baseline-waterfall__name">{{ entry.node }}</span>
                  <div class="baseline-waterfall__track">
                    <div
                      class="baseline-waterfall__bar"
                      :class="entry.isLongest ? 'baseline-waterfall__bar--longest' : ''"
                      :style="{ width: entry.ms !== null ? entry.pct + '%' : '0%' }"
                    />
                  </div>
                  <span class="baseline-waterfall__ms">{{ entry.ms !== null ? entry.ms + 'ms' : '—' }}</span>
                </div>
                <div class="baseline-waterfall__total">
                  Wall time: {{ detailRow.wall_time_ms != null ? Math.round(detailRow.wall_time_ms) + 'ms' : '—' }}
                </div>
              </div>
            </div>

            <!-- Generated intent -->
            <div v-if="detailRow.generated_intent" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Generated Intent</h3>
              <pre class="baseline-pre">{{ formatJson(detailRow.generated_intent) }}</pre>
            </div>

            <!-- Compiled SQL -->
            <div v-if="detailRow.compiled_sql" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Compiled SQL</h3>
              <pre class="baseline-pre baseline-pre--sql">{{ detailRow.compiled_sql }}</pre>
            </div>

            <!-- Response -->
            <div v-if="detailRow.response && Object.keys(detailRow.response).length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Response</h3>
              <pre class="baseline-pre">{{ formatJson(detailRow.response) }}</pre>
            </div>

            <!-- Token usage -->
            <div v-if="detailRow.input_tokens || detailRow.output_tokens" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Token Usage</h3>
              <div class="baseline-token-row">
                <div class="baseline-token-cell">
                  <span class="baseline-token-cell__label">Input</span>
                  <span class="baseline-token-cell__val">{{ detailRow.input_tokens || 0 }}</span>
                </div>
                <div class="baseline-token-cell">
                  <span class="baseline-token-cell__label">Output</span>
                  <span class="baseline-token-cell__val">{{ detailRow.output_tokens || 0 }}</span>
                </div>
                <div class="baseline-token-cell">
                  <span class="baseline-token-cell__label">Total</span>
                  <span class="baseline-token-cell__val">{{ (detailRow.input_tokens || 0) + (detailRow.output_tokens || 0) }}</span>
                </div>
                <div v-if="detailRow.llm_model" class="baseline-token-cell">
                  <span class="baseline-token-cell__label">Model</span>
                  <span class="baseline-token-cell__val baseline-token-cell__val--model">{{ detailRow.llm_model }}</span>
                </div>
                <div v-if="drawerQueryCost !== null" class="baseline-token-cell baseline-token-cell--cost">
                  <span class="baseline-token-cell__label">Est. Cost</span>
                  <span class="baseline-token-cell__val baseline-token-cell__val--cost">~${{ drawerQueryCost.toFixed(5) }}</span>
                </div>
              </div>
            </div>

            <!-- Debug -->
            <div v-if="detailRow.debug && Object.keys(detailRow.debug).length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Debug</h3>
              <pre class="baseline-pre">{{ formatJson(detailRow.debug) }}</pre>
            </div>

            <!-- Raw trace output -->
            <div v-if="detailRow.trace_output && detailRow.trace_output.length" class="baseline-drawer__section">
              <button class="baseline-trace-toggle" @click="traceOutputOpen = !traceOutputOpen">
                {{ traceOutputOpen ? '▾' : '▸' }} Raw Trace Output ({{ detailRow.trace_output.length }} lines)
              </button>
              <pre v-if="traceOutputOpen" class="baseline-pre baseline-pre--trace">{{ detailRow.trace_output.join('\n') }}</pre>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
import VueApexCharts from "vue3-apexcharts";

export default {
  name: "BaselineDashboard",

  components: { VueApexCharts },

  inject: ["$call"],

  data() {
    return {
      runs: [],
      loadingRuns: false,
      selectedRunId: null,
      currentRun: null,
      currentSummary: null,
      currentReport: null,

      selectedFixture: "baseline_queries.json",
      running: false,
      activeRunId: null,
      activeRunStatus: {},
      pollTimer: null,

      tableSearch: "",
      activeFilter: "all",

      detailRow: null,
      traceOutputOpen: false,
      globalError: "",
    };
  },

  computed: {
    visibleResults() {
      if (!this.currentReport || !this.currentReport.results) return [];
      return this.currentReport.results.filter((r) => !r.dependency_seed);
    },

    filteredResults() {
      let rows = this.visibleResults;

      if (this.activeFilter !== "all") {
        rows = rows.filter((r) => {
          switch (this.activeFilter) {
            case "mismatch": return !r.status_matches_expected;
            case "error": return r.status === "error" || r.status === "exception";
            case "no_rows": return r.status === "success" && (r.returned_rows === 0 || r.returned_rows === null);
            case "success": return r.status === "success";
            case "clarification": return r.status === "clarification_needed";
            case "blocked": return r.status === "blocked";
            case "greeting": return r.status === "greeting";
            default: return true;
          }
        });
      }

      const q = (this.tableSearch || "").toLowerCase().trim();
      if (q) {
        rows = rows.filter((r) => {
          return (
            (r.id || "").toLowerCase().includes(q) ||
            (r.message || "").toLowerCase().includes(q) ||
            (r.category || "").toLowerCase().includes(q) ||
            (r.status || "").toLowerCase().includes(q)
          );
        });
      }

      return rows;
    },

    filters() {
      return [
        { key: "all", label: "All" },
        { key: "mismatch", label: "Mismatches" },
        { key: "error", label: "Errors" },
        { key: "no_rows", label: "No Rows" },
        { key: "success", label: "Success" },
        { key: "clarification", label: "Clarification" },
        { key: "blocked", label: "Blocked" },
        { key: "greeting", label: "Greeting" },
      ];
    },

    statusChartSeries() {
      if (!this.currentSummary || !this.currentSummary.status_counts) return [];
      const colorMap = {
        success: "#22c55e",
        clarification_needed: "#f59e0b",
        blocked: "#6366f1",
        greeting: "#64748b",
        error: "#ef4444",
        exception: "#dc2626",
      };
      return Object.entries(this.currentSummary.status_counts).map(([label, value]) => ({
        label,
        value,
        color: colorMap[label] || "#94a3b8",
      }));
    },

    failingCategories() {
      return (this.currentSummary && this.currentSummary.top_failing_categories) || [];
    },

    maxFailCount() {
      if (!this.failingCategories.length) return 1;
      return Math.max(...this.failingCategories.map((c) => c.count), 1);
    },

    maxWallTime() {
      if (!this.visibleResults.length) return 1;
      return Math.max(...this.visibleResults.map((r) => r.wall_time_ms || 0), 1);
    },

    progressPct() {
      const completed = this.activeRunStatus.completed_queries || 0;
      const total = this.activeRunStatus.total_queries || 0;
      if (!total) return 0;
      return Math.min(100, Math.round((completed / total) * 100));
    },

    avgTimingDisplay() {
      const v = this.currentSummary && this.currentSummary.average_timing_ms;
      if (v == null) return "—";
      return v >= 1000 ? (v / 1000).toFixed(1) + "s" : Math.round(v) + "ms";
    },

    passRatePct() {
      const total = (this.currentSummary && this.currentSummary.total_queries) || 0;
      const success = (this.currentSummary && this.currentSummary.success_count) || 0;
      if (!total) return 0;
      return Math.round((success / total) * 100);
    },

    drawerQueryCost() {
      if (!this.detailRow) return null;
      return this.perQueryCost(this.detailRow);
    },

    tokensSummaryAvailable() {
      return !!(
        this.currentSummary &&
        (this.currentSummary.total_input_tokens || this.currentSummary.total_output_tokens)
      );
    },

    estimatedCost() {
      if (!this.tokensSummaryAvailable) return null;
      const model = (this.currentSummary.llm_model || "").toLowerCase();
      const PRICING = [
        { match: "gpt-4o-mini", input: 0.15, output: 0.60 },
        { match: "gpt-4o", input: 2.50, output: 10.00 },
        { match: "gpt-4-turbo", input: 10.00, output: 30.00 },
        { match: "gpt-4", input: 30.00, output: 60.00 },
        { match: "gpt-3.5", input: 0.50, output: 1.50 },
        { match: "claude-opus-4", input: 15.00, output: 75.00 },
        { match: "claude-opus-3", input: 15.00, output: 75.00 },
        { match: "claude-3-5-sonnet", input: 3.00, output: 15.00 },
        { match: "claude-sonnet-4", input: 3.00, output: 15.00 },
        { match: "claude-3-sonnet", input: 3.00, output: 15.00 },
        { match: "claude-3-5-haiku", input: 0.80, output: 4.00 },
        { match: "claude-haiku-4", input: 0.80, output: 4.00 },
        { match: "claude-3-haiku", input: 0.25, output: 1.25 },
      ];
      const pricing = PRICING.find((p) => model.includes(p.match));
      if (!pricing) return null;
      const inputCost =
        ((this.currentSummary.total_input_tokens || 0) / 1_000_000) * pricing.input;
      const outputCost =
        ((this.currentSummary.total_output_tokens || 0) / 1_000_000) * pricing.output;
      return { total: inputCost + outputCost, model: this.currentSummary.llm_model };
    },

    // ── ApexCharts: status donut ─────────────────────────
    statusDonutSeries() {
      if (!this.currentSummary || !this.currentSummary.status_counts) return [];
      return Object.values(this.currentSummary.status_counts);
    },
    statusDonutOptions() {
      const colorMap = {
        success: "#22c55e",
        clarification_needed: "#f59e0b",
        blocked: "#6366f1",
        greeting: "#64748b",
        error: "#ef4444",
        exception: "#dc2626",
      };
      const labels = this.currentSummary
        ? Object.keys(this.currentSummary.status_counts || {})
        : [];
      return {
        chart: { type: "donut", height: 220, toolbar: { show: false } },
        labels,
        colors: labels.map((l) => colorMap[l] || "#94a3b8"),
        legend: { position: "bottom", fontSize: "11px" },
        dataLabels: { enabled: true, style: { fontSize: "11px" } },
        tooltip: { y: { formatter: (v) => v + " queries" } },
        plotOptions: { pie: { donut: { size: "60%" } } },
      };
    },

    // ── ApexCharts: failing categories horizontal bar ────
    failingBarSeries() {
      if (!this.failingCategories.length) return [];
      return [{ name: "Failing", data: this.failingCategories.map((c) => c.count) }];
    },
    failingBarOptions() {
      const height = Math.max(120, this.failingCategories.length * 30);
      return {
        chart: { type: "bar", height, toolbar: { show: false } },
        plotOptions: { bar: { horizontal: true, barHeight: "60%" } },
        colors: ["#ef4444"],
        xaxis: {
          categories: this.failingCategories.map((c) => c.category),
          labels: { style: { fontSize: "11px" } },
        },
        yaxis: { labels: { style: { fontSize: "11px" } } },
        dataLabels: { enabled: false },
        tooltip: { y: { formatter: (v) => v + " queries" } },
        grid: { borderColor: "#f1f5f9" },
      };
    },

    // ── ApexCharts: wall time per query ──────────────────
    timingChartSeries() {
      if (!this.visibleResults.length) return [];
      return [{ name: "Wall Time (ms)", data: this.visibleResults.map((r) => r.wall_time_ms || 0) }];
    },
    timingChartOptions() {
      const colorFor = (r) => {
        if (!r.status_matches_expected) return "#9333ea";
        if (r.status === "success") return "#22c55e";
        if (r.status === "error" || r.status === "exception") return "#ef4444";
        return "#94a3b8";
      };
      return {
        chart: { type: "bar", height: 180, toolbar: { show: false }, animations: { enabled: false } },
        plotOptions: { bar: { columnWidth: "80%", distributed: true } },
        colors: this.visibleResults.map((r) => colorFor(r)),
        xaxis: {
          categories: this.visibleResults.map((r) => r.id || ""),
          labels: { rotate: -45, style: { fontSize: "10px" } },
        },
        yaxis: { labels: { style: { fontSize: "10px" }, formatter: (v) => Math.round(v) + "ms" } },
        legend: { show: false },
        dataLabels: { enabled: false },
        tooltip: { y: { formatter: (v) => v + "ms" }, x: { show: true } },
        grid: { borderColor: "#f1f5f9" },
      };
    },

    // ── ApexCharts: retries per query ────────────────────
    retriesChartSeries() {
      if (!this.visibleResults.length) return [];
      return [{ name: "Retries", data: this.visibleResults.map((r) => r.retries || 0) }];
    },
    retriesChartOptions() {
      return {
        chart: { type: "bar", height: 180, toolbar: { show: false }, animations: { enabled: false } },
        plotOptions: { bar: { columnWidth: "80%", distributed: true } },
        colors: this.visibleResults.map((r) => ((r.retries || 0) > 0 ? "#f59e0b" : "#22c55e")),
        xaxis: {
          categories: this.visibleResults.map((r) => r.id || ""),
          labels: { rotate: -45, style: { fontSize: "10px" } },
        },
        yaxis: { labels: { style: { fontSize: "10px" }, formatter: (v) => Math.round(v) } },
        legend: { show: false },
        dataLabels: { enabled: false },
        tooltip: { y: { formatter: (v) => v + " retries" } },
        grid: { borderColor: "#f1f5f9" },
      };
    },

    // ── ApexCharts: token usage per query (stacked) ──────
    tokenPerQuerySeries() {
      if (!this.visibleResults.length) return [];
      return [
        { name: "Input Tokens", data: this.visibleResults.map((r) => r.input_tokens || 0) },
        { name: "Output Tokens", data: this.visibleResults.map((r) => r.output_tokens || 0) },
      ];
    },
    tokenPerQueryOptions() {
      return {
        chart: {
          type: "bar",
          stacked: true,
          height: 200,
          toolbar: { show: false },
          animations: { enabled: false },
        },
        plotOptions: { bar: { columnWidth: "80%" } },
        colors: ["#6366f1", "#a78bfa"],
        xaxis: {
          categories: this.visibleResults.map((r) => r.id || ""),
          labels: { rotate: -45, style: { fontSize: "10px" } },
        },
        yaxis: { labels: { style: { fontSize: "10px" } } },
        legend: { position: "top", fontSize: "11px" },
        dataLabels: { enabled: false },
        tooltip: { shared: true, intersect: false },
        grid: { borderColor: "#f1f5f9" },
      };
    },

    // ── ApexCharts: avg tokens by category (stacked horiz)
    tokenByCategoryData() {
      if (!this.visibleResults.length) return [];
      const cats = {};
      for (const r of this.visibleResults) {
        const cat = r.category || "unknown";
        if (!cats[cat]) cats[cat] = { input: [], output: [] };
        cats[cat].input.push(r.input_tokens || 0);
        cats[cat].output.push(r.output_tokens || 0);
      }
      return Object.entries(cats)
        .map(([cat, v]) => {
          const avgInput = Math.round(v.input.reduce((a, b) => a + b, 0) / v.input.length);
          const avgOutput = Math.round(v.output.reduce((a, b) => a + b, 0) / v.output.length);
          return { category: cat, avgInput, avgOutput, avgTotal: avgInput + avgOutput };
        })
        .sort((a, b) => b.avgTotal - a.avgTotal);
    },
    tokenByCategorySeries() {
      return [
        { name: "Avg Input", data: this.tokenByCategoryData.map((d) => d.avgInput) },
        { name: "Avg Output", data: this.tokenByCategoryData.map((d) => d.avgOutput) },
      ];
    },
    tokenByCategoryOptions() {
      const height = Math.max(160, this.tokenByCategoryData.length * 30);
      return {
        chart: {
          type: "bar",
          stacked: true,
          height,
          toolbar: { show: false },
          animations: { enabled: false },
        },
        plotOptions: { bar: { horizontal: true, barHeight: "60%" } },
        colors: ["#6366f1", "#a78bfa"],
        xaxis: {
          categories: this.tokenByCategoryData.map((d) => d.category),
          labels: { style: { fontSize: "10px" } },
        },
        yaxis: { labels: { style: { fontSize: "10px" } } },
        legend: { position: "top", fontSize: "11px" },
        dataLabels: { enabled: false },
        tooltip: { shared: true, intersect: false },
        grid: { borderColor: "#f1f5f9" },
      };
    },

    // ── Node timing waterfall (for drawer) ───────────────
    nodeTimingWaterfall() {
      if (!this.detailRow) return [];
      const trace = this.detailRow.node_trace || [];
      const timing = this.detailRow.timing || {};
      const timingValues = Object.values(timing).filter((v) => typeof v === "number");
      const maxTime = timingValues.length ? Math.max(...timingValues) : 1;
      return trace.map((node) => ({
        node,
        ms: typeof timing[node] === "number" ? timing[node] : null,
        pct: typeof timing[node] === "number" ? Math.round((timing[node] / maxTime) * 100) : 0,
        isLongest:
          typeof timing[node] === "number" &&
          timing[node] === maxTime &&
          timingValues.length > 0,
      }));
    },
  },

  async mounted() {
    await this.loadRuns();
  },

  beforeUnmount() {
    this._stopPolling();
  },

  methods: {
    async loadRuns() {
      this.loadingRuns = true;
      try {
        const res = await this.$call("internal_bot.api.baseline.list_runs");
        this.runs = res.runs || [];
        if (this.runs.length && !this.selectedRunId) {
          await this.selectRun(this.runs[0].name);
        }
      } catch (e) {
        this.globalError = e?.messages?.[0] || "Failed to load baseline runs.";
      } finally {
        this.loadingRuns = false;
      }
    },

    async selectRun(runId) {
      this.selectedRunId = runId;
      try {
        const res = await this.$call("internal_bot.api.baseline.get_run", { run_id: runId });
        this.currentRun = res.run;
        this.currentSummary = res.summary;
        this.currentReport = res.report;
      } catch (e) {
        this.globalError = e?.messages?.[0] || "Failed to load run details.";
      }
    },

    async startRun() {
      this.globalError = "";
      this.running = true;
      try {
        const res = await this.$call("internal_bot.api.baseline.start_run", {
          fixture_name: this.selectedFixture,
        });
        this.activeRunId = res.run_id;
        this.activeRunStatus = { status: "Queued", completed_queries: 0, total_queries: 0 };
        await this.loadRuns();
        this._startPolling(res.run_id);
      } catch (e) {
        this.running = false;
        this.globalError = e?.messages?.[0] || "Failed to start baseline run.";
      }
    },

    _startPolling(runId) {
      this._stopPolling();
      this.pollTimer = setInterval(async () => {
        try {
          const status = await this.$call("internal_bot.api.baseline.get_run_status", {
            run_id: runId,
          });
          this.activeRunStatus = status;

          // Refresh the run list row (progress counter)
          const idx = this.runs.findIndex((r) => r.name === runId);
          if (idx !== -1) {
            this.runs[idx] = { ...this.runs[idx], ...status };
          }

          if (status.status === "Completed" || status.status === "Failed") {
            this._stopPolling();
            this.running = false;
            await this.loadRuns();
            await this.selectRun(runId);
          }
        } catch {
          // non-fatal, keep polling
        }
      }, 2000);
    },

    _stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    openDetail(row) {
      this.detailRow = row;
      this.traceOutputOpen = false;
    },

    perQueryCost(r) {
      if (!r) return null;
      const model = (
        (this.currentSummary && this.currentSummary.llm_model) ||
        r.llm_model ||
        ""
      ).toLowerCase();
      const PRICING = [
        { match: "gpt-4o-mini", input: 0.15, output: 0.60 },
        { match: "gpt-4o", input: 2.50, output: 10.00 },
        { match: "claude-opus-4", input: 15.00, output: 75.00 },
        { match: "claude-opus-3", input: 15.00, output: 75.00 },
        { match: "claude-3-5-sonnet", input: 3.00, output: 15.00 },
        { match: "claude-sonnet-4", input: 3.00, output: 15.00 },
        { match: "claude-3-sonnet", input: 3.00, output: 15.00 },
        { match: "claude-3-5-haiku", input: 0.80, output: 4.00 },
        { match: "claude-haiku-4", input: 0.80, output: 4.00 },
        { match: "claude-3-haiku", input: 0.25, output: 1.25 },
        { match: "gpt-4-turbo", input: 10.00, output: 30.00 },
        { match: "gpt-4", input: 30.00, output: 60.00 },
        { match: "gpt-3.5", input: 0.50, output: 1.50 },
      ];
      const pricing = PRICING.find((p) => model.includes(p.match));
      if (!pricing) return null;
      const inputTok = r.input_tokens || 0;
      const outputTok = r.output_tokens || 0;
      if (!inputTok && !outputTok) return null;
      return (inputTok / 1_000_000) * pricing.input + (outputTok / 1_000_000) * pricing.output;
    },

    fmtNum(n) {
      if (n == null || n === "—") return "—";
      const num = Number(n);
      if (isNaN(num)) return n;
      if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
      if (num >= 1_000) return (num / 1_000).toFixed(1) + "k";
      return num.toString();
    },

    sv(field) {
      return this.currentSummary != null && this.currentSummary[field] != null
        ? this.currentSummary[field]
        : "—";
    },

    barPct(count) {
      return Math.round((count / this.maxFailCount) * 100);
    },

    microBarHeight(ms) {
      const max = this.maxWallTime || 1;
      return Math.max(4, Math.round((ms / max) * 60));
    },

    microBarClass(r) {
      if (!r.status_matches_expected) return "baseline-micro-bar--mismatch";
      if (r.status === "success") return "baseline-micro-bar--ok";
      if (r.status === "error" || r.status === "exception") return "baseline-micro-bar--error";
      return "baseline-micro-bar--neutral";
    },

    statusClass(status) {
      const map = {
        success: "badge--success",
        Completed: "badge--success",
        Running: "badge--running",
        Queued: "badge--queued",
        blocked: "badge--blocked",
        clarification_needed: "badge--clarification",
        greeting: "badge--neutral",
        error: "badge--error",
        exception: "badge--error",
        Failed: "badge--error",
      };
      return map[status] || "badge--neutral";
    },

    formatDate(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    },

    formatJson(value) {
      try {
        return JSON.stringify(value, null, 2);
      } catch {
        return String(value);
      }
    },
  },
};
</script>

<style scoped>
/* ════════════════════════════════════════════════════════
   ELECTRIC BASELINE DASHBOARD
   ════════════════════════════════════════════════════════ */

/* ── Keyframes ───────────────────────────────────────── */
@keyframes cardSlideUp {
  from { opacity: 0; transform: translateY(18px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}
@keyframes progressGlow {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.7); }
}
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes glowPulse {
  0%, 100% { box-shadow: 0 0 8px rgba(99,102,241,0.3); }
  50%       { box-shadow: 0 0 20px rgba(99,102,241,0.6); }
}

/* ── Root & layout ───────────────────────────────────── */
.baseline-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 100vh;
  background: #f0f2f7;
  font-family: inherit;
  font-size: 14px;
  color: #1e293b;
}

.baseline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 24px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 55%, #312e81 100%);
  border-bottom: 1px solid #4338ca;
  flex-shrink: 0;
  flex-wrap: wrap;
  box-shadow: 0 4px 24px rgba(0,0,0,0.25);
  position: relative;
  z-index: 10;
}

.baseline-header__left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.baseline-header__title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(90deg, #e0e7ff, #c7d2fe, #a5b4fc);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
}

.baseline-back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  color: #818cf8;
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.baseline-back:hover { background: rgba(255,255,255,0.1); color: #e0e7ff; }
.baseline-back svg { width: 18px; height: 18px; }

.baseline-header__controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Form controls ───────────────────────────────────── */
.baseline-select {
  padding: 6px 10px;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 7px;
  background: rgba(255,255,255,0.1);
  backdrop-filter: blur(8px);
  font-size: 13px;
  color: #e0e7ff;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.baseline-select option { background: #1e1b4b; color: #e0e7ff; }
.baseline-select:hover { border-color: rgba(165,180,252,0.4); background: rgba(255,255,255,0.15); }
.baseline-select:disabled { opacity: 0.4; cursor: not-allowed; }

.baseline-btn {
  padding: 7px 18px;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.15s;
}
.baseline-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.baseline-btn--primary {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  box-shadow: 0 2px 12px rgba(99,102,241,0.45);
  font-weight: 600;
  letter-spacing: 0.01em;
  transition: box-shadow 0.2s, transform 0.15s, background 0.2s;
}
.baseline-btn--primary:not(:disabled):hover {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  box-shadow: 0 4px 20px rgba(99,102,241,0.6);
  transform: translateY(-1px);
}
.baseline-btn--primary:not(:disabled):active { transform: translateY(0); }

.baseline-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* ── Global error ────────────────────────────────────── */
.baseline-error {
  background: linear-gradient(90deg, #fee2e2, #fef2f2);
  color: #991b1b;
  padding: 10px 24px;
  font-size: 13px;
  border-bottom: 1px solid #fca5a5;
  font-weight: 500;
}

/* ── Progress bar ────────────────────────────────────── */
.baseline-progress-bar-wrap {
  position: relative;
  height: 5px;
  background: #1e1b4b;
  flex-shrink: 0;
  overflow: visible;
}
.baseline-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899, #6366f1);
  background-size: 200% 100%;
  animation: progressGlow 1.6s linear infinite;
  transition: width 0.5s ease;
  box-shadow: 0 0 10px rgba(99,102,241,0.7);
}
.baseline-progress-label {
  position: absolute;
  right: 16px;
  top: 8px;
  font-size: 11px;
  font-weight: 600;
  color: #6366f1;
  display: flex;
  align-items: center;
  gap: 6px;
}
.baseline-live-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  background: #22c55e;
  border-radius: 50%;
  animation: pulse 1.2s ease-in-out infinite;
  box-shadow: 0 0 6px rgba(34,197,94,0.7);
}

/* ── Body: sidebar + main ────────────────────────────── */
.baseline-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── History sidebar ─────────────────────────────────── */
.baseline-history {
  width: 210px;
  min-width: 165px;
  border-right: 1px solid #dde3ef;
  background: #fff;
  overflow-y: auto;
  flex-shrink: 0;
  padding: 8px 0;
  box-shadow: 2px 0 8px rgba(0,0,0,0.04);
}
.baseline-history__label {
  font-size: 10px;
  font-weight: 700;
  color: #a5b4fc;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  padding: 6px 14px 8px;
  margin: 0;
}
.baseline-history__item {
  padding: 9px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.12s, border-color 0.12s;
}
.baseline-history__item:hover { background: #f5f6fb; }
.baseline-history__item--active {
  background: linear-gradient(90deg, #eef2ff 0%, #f5f7ff 100%);
  border-left-color: #6366f1;
}
.baseline-history__item-fixture {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
  word-break: break-all;
}
.baseline-history__item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 3px;
  flex-wrap: wrap;
}
.baseline-history__item-date {
  font-size: 11px;
  color: #94a3b8;
}
.baseline-history__item-counts {
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  margin-top: 2px;
}
.baseline-history__empty {
  font-size: 12px;
  color: #94a3b8;
  padding: 14px;
  margin: 0;
}

/* ── Main content ────────────────────────────────────── */
.baseline-main {
  flex: 1;
  overflow-y: auto;
  padding: 22px 24px;
  min-width: 0;
}
.baseline-main--empty {
  display: flex;
  align-items: center;
  justify-content: center;
}
.baseline-empty-state {
  color: #94a3b8;
  font-size: 14px;
}

/* ── Sections ────────────────────────────────────────── */
.baseline-section {
  margin-bottom: 26px;
}
.baseline-section__title {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  margin: 0 0 12px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ── Summary cards ───────────────────────────────────── */
.baseline-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.baseline-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 18px;
  min-width: 88px;
  text-align: center;
  animation: cardSlideUp 0.38s cubic-bezier(0.22,1,0.36,1) both;
  transition: transform 0.18s, box-shadow 0.18s;
  box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}
.baseline-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0,0,0,0.10);
}
.baseline-cards > *:nth-child(1)  { animation-delay: 0.04s; }
.baseline-cards > *:nth-child(2)  { animation-delay: 0.08s; }
.baseline-cards > *:nth-child(3)  { animation-delay: 0.12s; }
.baseline-cards > *:nth-child(4)  { animation-delay: 0.16s; }
.baseline-cards > *:nth-child(5)  { animation-delay: 0.20s; }
.baseline-cards > *:nth-child(6)  { animation-delay: 0.24s; }
.baseline-cards > *:nth-child(7)  { animation-delay: 0.28s; }
.baseline-cards > *:nth-child(8)  { animation-delay: 0.32s; }
.baseline-cards > *:nth-child(9)  { animation-delay: 0.36s; }
.baseline-cards > *:nth-child(10) { animation-delay: 0.40s; }
.baseline-cards > *:nth-child(11) { animation-delay: 0.44s; }
.baseline-cards > *:nth-child(12) { animation-delay: 0.48s; }
.baseline-cards > *:nth-child(13) { animation-delay: 0.52s; }
.baseline-cards > *:nth-child(14) { animation-delay: 0.56s; }
.baseline-cards > *:nth-child(15) { animation-delay: 0.60s; }

.baseline-card__value {
  font-size: 24px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.baseline-card__label {
  font-size: 10px;
  font-weight: 600;
  color: #94a3b8;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.baseline-card--success {
  background: linear-gradient(145deg, #f0fdf4, #dcfce7);
  border-color: #86efac;
  box-shadow: 0 2px 8px rgba(34,197,94,0.12);
}
.baseline-card--success:hover { box-shadow: 0 6px 20px rgba(34,197,94,0.22); }
.baseline-card--success .baseline-card__value { color: #15803d; }

.baseline-card--error {
  background: linear-gradient(145deg, #fef2f2, #fee2e2);
  border-color: #fca5a5;
  box-shadow: 0 2px 8px rgba(239,68,68,0.12);
}
.baseline-card--error:hover { box-shadow: 0 6px 20px rgba(239,68,68,0.22); }
.baseline-card--error .baseline-card__value { color: #dc2626; }

.baseline-card--warn {
  background: linear-gradient(145deg, #fffbeb, #fef3c7);
  border-color: #fcd34d;
  box-shadow: 0 2px 8px rgba(245,158,11,0.12);
}
.baseline-card--warn:hover { box-shadow: 0 6px 20px rgba(245,158,11,0.22); }
.baseline-card--warn .baseline-card__value { color: #b45309; }

.baseline-card--neutral {
  background: linear-gradient(145deg, #f8fafc, #f1f5f9);
  border-color: #cbd5e1;
}
.baseline-card--neutral .baseline-card__value { color: #475569; }

.baseline-card--mismatch {
  background: linear-gradient(145deg, #fdf4ff, #fae8ff);
  border-color: #d8b4fe;
  box-shadow: 0 2px 8px rgba(168,85,247,0.12);
}
.baseline-card--mismatch:hover { box-shadow: 0 6px 20px rgba(168,85,247,0.22); }
.baseline-card--mismatch .baseline-card__value { color: #9333ea; }

.baseline-card--token {
  background: linear-gradient(145deg, #eef2ff, #e0e7ff);
  border-color: #a5b4fc;
  box-shadow: 0 2px 8px rgba(99,102,241,0.12);
}
.baseline-card--token:hover { box-shadow: 0 6px 20px rgba(99,102,241,0.22); }
.baseline-card--token .baseline-card__value { color: #4f46e5; }

.baseline-card--cost {
  background: linear-gradient(145deg, #faf5ff, #ede9fe);
  border-color: #c4b5fd;
  box-shadow: 0 2px 8px rgba(139,92,246,0.15);
  cursor: help;
}
.baseline-card--cost:hover { box-shadow: 0 6px 20px rgba(139,92,246,0.28); }
.baseline-card--cost .baseline-card__value { color: #7c3aed; }

/* ── Charts row ──────────────────────────────────────── */
.baseline-charts-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.baseline-chart-box {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 16px 18px;
  flex: 1;
  min-width: 180px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  transition: box-shadow 0.2s, transform 0.2s;
}
.baseline-chart-box:hover {
  box-shadow: 0 6px 20px rgba(99,102,241,0.10);
  transform: translateY(-1px);
}
.baseline-chart-box--wide {
  flex: 2;
  min-width: 260px;
}
.baseline-chart-box__title {
  font-size: 11px;
  font-weight: 700;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin: 0 0 12px;
}
.baseline-chart-empty {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
  padding: 16px 0;
  text-align: center;
}

/* ── Table ───────────────────────────────────────────── */
.baseline-table-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.baseline-search {
  padding: 7px 12px;
  border: 1px solid #dde3ef;
  border-radius: 8px;
  font-size: 13px;
  width: 230px;
  background: #fff;
  color: #1e293b;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.baseline-search:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.12);
}
.baseline-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.baseline-filter-btn {
  padding: 4px 11px;
  border: 1px solid #dde3ef;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.14s;
}
.baseline-filter-btn:hover { background: #f0f0fb; border-color: #a5b4fc; color: #4f46e5; }
.baseline-filter-btn--active {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 2px 8px rgba(99,102,241,0.3);
}

.baseline-table-wrap {
  overflow-x: auto;
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.baseline-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.baseline-table thead tr {
  background: linear-gradient(90deg, #f8faff, #f3f4fd);
  border-bottom: 1px solid #e8edf5;
}
.baseline-table th {
  padding: 9px 12px;
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  white-space: nowrap;
}
.baseline-table__row {
  cursor: pointer;
  border-bottom: 1px solid #f3f4fd;
  transition: background 0.12s;
}
.baseline-table__row:last-child { border-bottom: none; }
.baseline-table__row:hover { background: #f0f2ff; }
.baseline-table__row--mismatch { background: #fdf4ff; }
.baseline-table__row--mismatch:hover { background: #f5e8ff; }
.baseline-table__row--seed { opacity: 0.5; }
.baseline-table td {
  padding: 9px 12px;
  vertical-align: middle;
  color: #1e293b;
}
.baseline-table__id { font-family: monospace; font-size: 12px; font-weight: 600; color: #4f46e5; }
.baseline-table__schema {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  font-size: 12px;
}
.baseline-table__empty {
  text-align: center;
  color: #94a3b8;
  padding: 28px;
  font-size: 13px;
}

/* ── Status badges ───────────────────────────────────── */
.baseline-status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.badge--success {
  background: linear-gradient(135deg, #dcfce7, #bbf7d0);
  color: #15803d;
  box-shadow: 0 1px 4px rgba(34,197,94,0.2);
}
.badge--error {
  background: linear-gradient(135deg, #fee2e2, #fecaca);
  color: #b91c1c;
  box-shadow: 0 1px 4px rgba(239,68,68,0.2);
}
.badge--blocked {
  background: linear-gradient(135deg, #ede9fe, #ddd6fe);
  color: #6d28d9;
  box-shadow: 0 1px 4px rgba(109,40,217,0.15);
}
.badge--clarification {
  background: linear-gradient(135deg, #fef9c3, #fef08a);
  color: #92400e;
  box-shadow: 0 1px 4px rgba(234,179,8,0.2);
}
.badge--neutral { background: #f1f5f9; color: #475569; }
.badge--running {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #1d4ed8;
  animation: glowPulse 1.5s ease-in-out infinite;
}
.badge--queued { background: linear-gradient(135deg, #f0fdf4, #dcfce7); color: #166534; }
.badge--mismatch { background: linear-gradient(135deg, #fdf4ff, #fae8ff); color: #7e22ce; }

/* ── Detail drawer ───────────────────────────────────── */
.baseline-drawer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
}
.baseline-drawer__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15,23,42,0.45);
  backdrop-filter: blur(2px);
}
.baseline-drawer__panel {
  position: relative;
  width: min(600px, 95vw);
  height: 100%;
  background: #fff;
  box-shadow: -8px 0 40px rgba(0,0,0,0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.baseline-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
  border-bottom: 1px solid #312e81;
  flex-shrink: 0;
}
.baseline-drawer__title {
  font-size: 14px;
  font-weight: 700;
  margin: 0;
  background: linear-gradient(90deg, #e0e7ff, #c7d2fe);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.baseline-drawer__close {
  background: rgba(255,255,255,0.1);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  color: #818cf8;
  transition: background 0.15s, color 0.15s;
}
.baseline-drawer__close:hover { background: rgba(255,255,255,0.2); color: #e0e7ff; }
.baseline-drawer__close svg { width: 16px; height: 16px; }


.baseline-drawer__section {
  margin-top: 16px;
  border-top: 1px solid #f1f5f9;
  padding-top: 14px;
}
.baseline-drawer__section-title {
  font-size: 10px;
  font-weight: 800;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  margin: 0 0 10px;
}


/* ── Pre blocks ──────────────────────────────────────── */
.baseline-pre {
  background: #f8fafc;
  border: 1px solid #e8edf5;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 11px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
  color: #334155;
  margin: 0;
  line-height: 1.6;
}
.baseline-pre--sql {
  background: #f0f4ff;
  color: #1e40af;
  border-color: #bfdbfe;
}

/* ── Drawer transition ───────────────────────────────── */
.drawer-enter-active, .drawer-leave-active { transition: opacity 0.2s ease; }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-active .baseline-drawer__panel,
.drawer-leave-active .baseline-drawer__panel { transition: transform 0.2s ease; }
.drawer-enter-from .baseline-drawer__panel,
.drawer-leave-to .baseline-drawer__panel { transform: translateX(100%); }

/* ── Token columns in table ──────────────────────────── */
.baseline-table__tokens {
  font-size: 12px;
  color: #6366f1;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

/* ── Node timing waterfall ───────────────────────────── */
.baseline-waterfall {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.baseline-waterfall__row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.baseline-waterfall__row--longest {
  background: linear-gradient(90deg, #faf5ff, transparent);
  border-radius: 6px;
  padding: 2px 4px;
  margin: 0 -4px;
}
.baseline-waterfall__row--longest .baseline-waterfall__name {
  font-weight: 700;
  color: #7c3aed;
}
.baseline-waterfall__name {
  flex-shrink: 0;
  width: 148px;
  font-family: monospace;
  font-size: 11px;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.baseline-waterfall__track {
  flex: 1;
  height: 10px;
  background: #f1f5f9;
  border-radius: 5px;
  overflow: hidden;
}
.baseline-waterfall__bar {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 5px;
  transition: width 0.5s cubic-bezier(0.22,1,0.36,1);
  min-width: 3px;
}
.baseline-waterfall__bar--longest {
  background: linear-gradient(90deg, #7c3aed, #ec4899);
  box-shadow: 0 0 8px rgba(124,58,237,0.4);
}
.baseline-waterfall__ms {
  flex-shrink: 0;
  width: 62px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #64748b;
  font-size: 11px;
  font-weight: 500;
}
.baseline-waterfall__total {
  margin-top: 6px;
  text-align: right;
  font-size: 11px;
  font-weight: 600;
  color: #6366f1;
  border-top: 1px solid #f1f5f9;
  padding-top: 6px;
}

/* ── Token breakdown in drawer ───────────────────────── */
.baseline-token-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.baseline-token-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: linear-gradient(145deg, #eef2ff, #e0e7ff);
  border: 1px solid #c7d2fe;
  border-radius: 8px;
  padding: 10px 16px;
  min-width: 72px;
  transition: transform 0.15s, box-shadow 0.15s;
}
.baseline-token-cell:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99,102,241,0.2);
}
.baseline-token-cell__label {
  font-size: 9px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  color: #818cf8;
}
.baseline-token-cell__val {
  font-size: 18px;
  font-weight: 800;
  color: #4f46e5;
  margin-top: 3px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.baseline-token-cell__val--model {
  font-size: 11px;
  color: #6366f1;
  font-family: monospace;
  font-weight: 600;
}

/* ── Trace output toggle ─────────────────────────────── */
.baseline-trace-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  border: 1px solid #c7d2fe;
  cursor: pointer;
  font-size: 12px;
  color: #4f46e5;
  padding: 5px 12px;
  border-radius: 6px;
  margin-bottom: 10px;
  font-weight: 600;
  transition: background 0.15s, box-shadow 0.15s;
}
.baseline-trace-toggle:hover {
  background: linear-gradient(135deg, #e0e7ff, #c7d2fe);
  box-shadow: 0 2px 8px rgba(99,102,241,0.2);
}
.baseline-pre--trace {
  max-height: 300px;
  overflow-y: auto;
  font-size: 10px;
  line-height: 1.6;
  background: #0f172a;
  color: #a5b4fc;
  border-color: #312e81;
}

/* ── Drawer body refinements ─────────────────────────── */
.baseline-drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 20px;
  background: #fafbff;
}
.baseline-drawer__row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 9px;
  font-size: 13px;
}
.baseline-drawer__key {
  flex-shrink: 0;
  width: 112px;
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding-top: 2px;
}
.baseline-drawer__val {
  flex: 1;
  color: #1e293b;
  word-break: break-word;
  font-size: 13px;
}
.baseline-drawer__val--error {
  color: #dc2626;
  background: #fef2f2;
  border-radius: 4px;
  padding: 2px 6px;
}

/* ── Detail table ────────────────────────────────────── */
.baseline-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.baseline-detail-table tr { border-bottom: 1px solid #f1f5f9; }
.baseline-detail-table td { padding: 5px 6px; color: #1e293b; }
.baseline-detail-table__key { color: #6366f1; width: 140px; font-family: monospace; font-weight: 600; }

/* ── Cost column in table ────────────────────────────── */
.baseline-table__cost {
  font-size: 11px;
  color: #b45309;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  white-space: nowrap;
}

/* ── Cost cell in drawer token row ───────────────────── */
.baseline-token-cell--cost {
  background: linear-gradient(145deg, #fef9c3, #fef3c7);
  border-color: #fcd34d;
}
.baseline-token-cell__val--cost {
  font-size: 14px;
  color: #92400e;
  font-family: monospace;
  font-weight: 700;
}

/* ════════════════════════════════════════════════════════
   KPI ZONES & CARDS
   ════════════════════════════════════════════════════════ */

/* ── Zone containers ─────────────────────────────────── */
.kpi-zone {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #e8edf5;
  padding: 18px 20px;
  margin-bottom: 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04);
}
.kpi-zone__header {
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #94a3b8;
  margin: 0 0 14px;
}
.kpi-zone--dark {
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 55%, #1a1042 100%);
  border-color: #312e81;
}
.kpi-zone--dark .kpi-zone__header {
  color: #818cf8;
}

/* Primary row: featured card + 3 equal */
.kpi-row--primary {
  display: grid;
  grid-template-columns: 1.6fr 1fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}
/* Secondary row: compact stats */
.kpi-row--secondary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
/* Dark zone card row */
.kpi-zone__cards {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* ── KPI Card Base ───────────────────────────────────── */
.kpi {
  position: relative;
  overflow: hidden;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e8edf5;
  border-top: 3px solid #e2e8f0;
  animation: cardSlideUp 0.38s cubic-bezier(0.22,1,0.36,1) both;
  transition: transform 0.18s, box-shadow 0.18s;
  box-shadow: 0 2px 6px rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kpi:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0,0,0,0.10);
}

/* Ghost SVG watermark */
.kpi__icon {
  position: absolute;
  right: 10px;
  bottom: 8px;
  width: 40px;
  height: 40px;
  opacity: 0.07;
  pointer-events: none;
  flex-shrink: 0;
}

.kpi__label {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.2;
}
.kpi__value {
  font-size: 28px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.kpi__sub {
  font-size: 10px;
  color: #94a3b8;
  font-weight: 500;
}
.kpi__accent {
  font-weight: 900;
}

/* Pass-rate bar */
.kpi__bar {
  height: 4px;
  background: #f1f5f9;
  border-radius: 2px;
  overflow: hidden;
  margin-top: 4px;
}
.kpi__bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #22c55e, #4ade80);
  border-radius: 2px;
  transition: width 0.8s cubic-bezier(0.22,1,0.36,1);
}

/* ── KPI stagger delays ──────────────────────────────── */
.kpi-row--primary .kpi:nth-child(1) { animation-delay: 0.04s; }
.kpi-row--primary .kpi:nth-child(2) { animation-delay: 0.10s; }
.kpi-row--primary .kpi:nth-child(3) { animation-delay: 0.16s; }
.kpi-row--primary .kpi:nth-child(4) { animation-delay: 0.22s; }
.kpi-row--secondary .kpi:nth-child(1) { animation-delay: 0.06s; }
.kpi-row--secondary .kpi:nth-child(2) { animation-delay: 0.10s; }
.kpi-row--secondary .kpi:nth-child(3) { animation-delay: 0.14s; }
.kpi-row--secondary .kpi:nth-child(4) { animation-delay: 0.18s; }
.kpi-row--secondary .kpi:nth-child(5) { animation-delay: 0.22s; }
.kpi-row--secondary .kpi:nth-child(6) { animation-delay: 0.26s; }
.kpi-zone--dark .kpi:nth-child(1) { animation-delay: 0.04s; }
.kpi-zone--dark .kpi:nth-child(2) { animation-delay: 0.10s; }
.kpi-zone--dark .kpi:nth-child(3) { animation-delay: 0.16s; }

/* ── Featured card ───────────────────────────────────── */
.kpi--featured {
  border-top-color: #6366f1;
  box-shadow: 0 2px 10px rgba(99,102,241,0.10);
}
.kpi--featured .kpi__value { font-size: 36px; }
.kpi--featured .kpi__icon { opacity: 0.06; }

/* ── Colour stripe variants ──────────────────────────── */
.kpi--success { border-top-color: #22c55e; }
.kpi--success .kpi__value { color: #15803d; }
.kpi--success .kpi__icon { opacity: 0.12; color: #22c55e; }

.kpi--error { border-top-color: #ef4444; }
.kpi--error .kpi__value { color: #dc2626; }
.kpi--error .kpi__icon { opacity: 0.12; color: #ef4444; }

.kpi--mismatch { border-top-color: #a855f7; }
.kpi--mismatch .kpi__value { color: #9333ea; }
.kpi--mismatch .kpi__icon { opacity: 0.12; color: #a855f7; }

.kpi--warn { border-top-color: #f59e0b; }
.kpi--warn .kpi__value { color: #b45309; }

.kpi--slate { border-top-color: #94a3b8; }
.kpi--slate .kpi__value { color: #475569; }

.kpi--blue { border-top-color: #3b82f6; }
.kpi--blue .kpi__value { color: #1d4ed8; }
.kpi--blue .kpi__icon { opacity: 0.10; color: #3b82f6; }

/* ── Compact variant (secondary row) ────────────────── */
.kpi--compact {
  padding: 10px 14px;
  flex: 1;
  min-width: 90px;
}
.kpi--compact .kpi__value { font-size: 20px; }
.kpi--compact .kpi__icon { width: 28px; height: 28px; }

/* ── Dark KPI cards ──────────────────────────────────── */
.kpi--dark {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.09);
  border-top: 3px solid rgba(255,255,255,0.14);
  flex: 1;
  min-width: 140px;
}
.kpi--dark .kpi__label { color: rgba(255,255,255,0.45); }
.kpi--dark .kpi__value { color: #f1f5f9; }
.kpi--dark .kpi__sub { color: rgba(255,255,255,0.35); }
.kpi--dark:hover {
  background: rgba(255,255,255,0.08);
  box-shadow: 0 6px 24px rgba(0,0,0,0.35);
}

/* Dark card accent colours */
.kpi--electric-blue { border-top-color: #60a5fa; }
.kpi--electric-blue .kpi__value { color: #93c5fd; }
.kpi--electric-blue .kpi__accent { color: #60a5fa; }

.kpi--violet { border-top-color: #a78bfa; }
.kpi--violet .kpi__value { color: #c4b5fd; }
.kpi--violet .kpi__accent { color: #a78bfa; }

.kpi--gold { border-top-color: #fbbf24; }
.kpi--gold .kpi__value { color: #fcd34d; }
.kpi--gold .kpi__accent { color: #fbbf24; }

/* ── Responsive ──────────────────────────────────────── */
@media (max-width: 900px) {
  .kpi-row--primary {
    grid-template-columns: 1fr 1fr;
  }
}

/* ── Responsive ──────────────────────────────────────── */
@media (max-width: 640px) {
  .baseline-history { width: 140px; min-width: 120px; }
  .baseline-main { padding: 14px; }
  .baseline-cards { gap: 8px; }
  .baseline-card { min-width: 72px; padding: 10px; }
  .baseline-card__value { font-size: 20px; }
  .baseline-search { width: 160px; }
  .baseline-charts-row { flex-direction: column; }
}
</style>
