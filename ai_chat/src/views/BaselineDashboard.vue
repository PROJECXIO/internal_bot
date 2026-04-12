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
      <span class="baseline-progress-label">{{ activeRunStatus.completed_queries || 0 }} / {{ activeRunStatus.total_queries || '?' }}</span>
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

        <!-- Summary cards -->
        <section class="baseline-section">
          <h2 class="baseline-section__title">Summary</h2>
          <div class="baseline-cards">
            <div class="baseline-card">
              <div class="baseline-card__value">{{ sv('total_queries') }}</div>
              <div class="baseline-card__label">Total</div>
            </div>
            <div class="baseline-card baseline-card--success">
              <div class="baseline-card__value">{{ sv('success_count') }}</div>
              <div class="baseline-card__label">Success</div>
            </div>
            <div class="baseline-card baseline-card--warn">
              <div class="baseline-card__value">{{ sv('clarification_count') }}</div>
              <div class="baseline-card__label">Clarification</div>
            </div>
            <div class="baseline-card baseline-card--neutral">
              <div class="baseline-card__value">{{ sv('blocked_count') }}</div>
              <div class="baseline-card__label">Blocked</div>
            </div>
            <div class="baseline-card baseline-card--neutral">
              <div class="baseline-card__value">{{ sv('greeting_count') }}</div>
              <div class="baseline-card__label">Greeting</div>
            </div>
            <div class="baseline-card baseline-card--error">
              <div class="baseline-card__value">{{ sv('error_count') }}</div>
              <div class="baseline-card__label">Errors</div>
            </div>
            <div class="baseline-card baseline-card--mismatch">
              <div class="baseline-card__value">{{ (currentSummary && currentSummary.status_mismatches && currentSummary.status_mismatches.length) || 0 }}</div>
              <div class="baseline-card__label">Mismatches</div>
            </div>
            <div class="baseline-card baseline-card--neutral">
              <div class="baseline-card__value">{{ (currentSummary && currentSummary.queries_with_no_rows && currentSummary.queries_with_no_rows.length) || 0 }}</div>
              <div class="baseline-card__label">No Rows</div>
            </div>
            <div class="baseline-card">
              <div class="baseline-card__value">{{ sv('average_retries') }}</div>
              <div class="baseline-card__label">Avg Retries</div>
            </div>
            <div class="baseline-card">
              <div class="baseline-card__value">{{ avgTimingDisplay }}</div>
              <div class="baseline-card__label">Avg Time</div>
            </div>
          </div>
        </section>

        <!-- Charts -->
        <section class="baseline-section baseline-charts-row">
          <!-- Status distribution -->
          <div class="baseline-chart-box">
            <h3 class="baseline-chart-box__title">Status Distribution</h3>
            <div v-if="statusChartSeries.length" class="baseline-chart-donut">
              <div
                v-for="(seg, i) in statusChartSeries"
                :key="seg.label"
                class="baseline-chart-donut__row"
              >
                <span class="baseline-chart-donut__swatch" :style="{ background: seg.color }" />
                <span class="baseline-chart-donut__label">{{ seg.label }}</span>
                <span class="baseline-chart-donut__val">{{ seg.value }}</span>
              </div>
            </div>
            <p v-else class="baseline-chart-empty">No data</p>
          </div>

          <!-- Top failing categories -->
          <div class="baseline-chart-box">
            <h3 class="baseline-chart-box__title">Top Failing Categories</h3>
            <div v-if="failingCategories.length" class="baseline-bar-chart">
              <div
                v-for="cat in failingCategories"
                :key="cat.category"
                class="baseline-bar-chart__row"
              >
                <span class="baseline-bar-chart__label">{{ cat.category }}</span>
                <div class="baseline-bar-chart__track">
                  <div class="baseline-bar-chart__fill baseline-bar-chart__fill--error" :style="{ width: barPct(cat.count) + '%' }" />
                </div>
                <span class="baseline-bar-chart__val">{{ cat.count }}</span>
              </div>
            </div>
            <p v-else class="baseline-chart-empty">No failing categories</p>
          </div>
        </section>

        <!-- Timing & retries mini-charts -->
        <section class="baseline-section baseline-charts-row" v-if="visibleResults.length">
          <!-- Timing by query -->
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Wall Time by Query (ms)</h3>
            <div class="baseline-micro-bars">
              <div
                v-for="r in visibleResults"
                :key="r.id"
                class="baseline-micro-bar"
                :title="`${r.id}: ${r.wall_time_ms}ms`"
                :style="{ height: microBarHeight(r.wall_time_ms) + 'px' }"
                :class="microBarClass(r)"
              />
            </div>
          </div>

          <!-- Retries by query -->
          <div class="baseline-chart-box baseline-chart-box--wide">
            <h3 class="baseline-chart-box__title">Retries by Query</h3>
            <div class="baseline-micro-bars">
              <div
                v-for="r in visibleResults"
                :key="r.id"
                class="baseline-micro-bar"
                :title="`${r.id}: ${r.retries} retries`"
                :style="{ height: Math.max(4, (r.retries || 0) * 20) + 'px' }"
                :class="r.retries > 0 ? 'baseline-micro-bar--warn' : 'baseline-micro-bar--ok'"
              />
            </div>
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
                </tr>
                <tr v-if="!filteredResults.length">
                  <td colspan="9" class="baseline-table__empty">No matching queries.</td>
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

            <!-- Node trace -->
            <div v-if="detailRow.node_trace && detailRow.node_trace.length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Node Trace</h3>
              <div class="baseline-trace">
                <span v-for="(node, i) in detailRow.node_trace" :key="i" class="baseline-trace__node">{{ node }}</span>
              </div>
            </div>

            <!-- Timing -->
            <div v-if="detailRow.timing && Object.keys(detailRow.timing).length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Timing (ms)</h3>
              <table class="baseline-detail-table">
                <tbody>
                  <tr v-for="(val, key) in detailRow.timing" :key="key">
                    <td class="baseline-detail-table__key">{{ key }}</td>
                    <td>{{ val }}</td>
                  </tr>
                </tbody>
              </table>
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

            <!-- Debug -->
            <div v-if="detailRow.debug && Object.keys(detailRow.debug).length" class="baseline-drawer__section">
              <h3 class="baseline-drawer__section-title">Debug</h3>
              <pre class="baseline-pre">{{ formatJson(detailRow.debug) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
export default {
  name: "BaselineDashboard",

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
/* ── Root & layout ───────────────────────────────────── */
.baseline-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 100vh;
  background: #f8fafc;
  font-family: inherit;
  font-size: 14px;
  color: #1e293b;
}

.baseline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.baseline-header__left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.baseline-header__title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.baseline-back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  color: #64748b;
  text-decoration: none;
  transition: background 0.15s;
}
.baseline-back:hover { background: #f1f5f9; }
.baseline-back svg { width: 18px; height: 18px; }

.baseline-header__controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Form controls ───────────────────────────────────── */
.baseline-select {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  color: #1e293b;
  cursor: pointer;
}
.baseline-select:disabled { opacity: 0.5; cursor: not-allowed; }

.baseline-btn {
  padding: 6px 16px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.15s;
}
.baseline-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.baseline-btn--primary {
  background: #6366f1;
  color: #fff;
}
.baseline-btn--primary:not(:disabled):hover { background: #4f46e5; }

.baseline-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Global error ────────────────────────────────────── */
.baseline-error {
  background: #fee2e2;
  color: #991b1b;
  padding: 10px 20px;
  font-size: 13px;
  border-bottom: 1px solid #fca5a5;
}

/* ── Progress bar ────────────────────────────────────── */
.baseline-progress-bar-wrap {
  position: relative;
  height: 6px;
  background: #e2e8f0;
  flex-shrink: 0;
}
.baseline-progress-bar {
  height: 100%;
  background: #6366f1;
  transition: width 0.4s ease;
}
.baseline-progress-label {
  position: absolute;
  right: 12px;
  top: 8px;
  font-size: 11px;
  color: #64748b;
}

/* ── Body: sidebar + main ────────────────────────────── */
.baseline-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── History sidebar ─────────────────────────────────── */
.baseline-history {
  width: 200px;
  min-width: 160px;
  border-right: 1px solid #e2e8f0;
  background: #fff;
  overflow-y: auto;
  flex-shrink: 0;
  padding: 8px 0;
}
.baseline-history__label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 4px 12px 8px;
  margin: 0;
}
.baseline-history__item {
  padding: 8px 12px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.12s, border-color 0.12s;
}
.baseline-history__item:hover { background: #f8fafc; }
.baseline-history__item--active {
  background: #eff6ff;
  border-left-color: #6366f1;
}
.baseline-history__item-fixture {
  font-size: 12px;
  font-weight: 500;
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
  color: #64748b;
  margin-top: 2px;
}
.baseline-history__empty {
  font-size: 12px;
  color: #94a3b8;
  padding: 12px;
  margin: 0;
}

/* ── Main content ────────────────────────────────────── */
.baseline-main {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
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
  margin-bottom: 24px;
}
.baseline-section__title {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 10px;
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
  border-radius: 8px;
  padding: 12px 16px;
  min-width: 90px;
  text-align: center;
}
.baseline-card__value {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.1;
}
.baseline-card__label {
  font-size: 11px;
  color: #64748b;
  margin-top: 3px;
}
.baseline-card--success .baseline-card__value { color: #16a34a; }
.baseline-card--error .baseline-card__value { color: #dc2626; }
.baseline-card--warn .baseline-card__value { color: #d97706; }
.baseline-card--neutral .baseline-card__value { color: #475569; }
.baseline-card--mismatch .baseline-card__value { color: #9333ea; }

/* ── Charts row ──────────────────────────────────────── */
.baseline-charts-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.baseline-chart-box {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  flex: 1;
  min-width: 180px;
}
.baseline-chart-box--wide {
  flex: 2;
  min-width: 260px;
}
.baseline-chart-box__title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin: 0 0 12px;
}
.baseline-chart-empty {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
}

/* Donut-style legend */
.baseline-chart-donut__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}
.baseline-chart-donut__swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.baseline-chart-donut__label { flex: 1; color: #475569; }
.baseline-chart-donut__val { font-weight: 600; color: #1e293b; }

/* Horizontal bar chart */
.baseline-bar-chart__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}
.baseline-bar-chart__label {
  width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
  flex-shrink: 0;
}
.baseline-bar-chart__track {
  flex: 1;
  height: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
}
.baseline-bar-chart__fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s;
}
.baseline-bar-chart__fill--error { background: #ef4444; }
.baseline-bar-chart__val { font-weight: 600; color: #1e293b; width: 20px; text-align: right; }

/* Micro bars (timing/retries) */
.baseline-micro-bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 68px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.baseline-micro-bar {
  flex-shrink: 0;
  width: 10px;
  min-height: 4px;
  border-radius: 2px 2px 0 0;
  cursor: pointer;
  transition: opacity 0.1s;
}
.baseline-micro-bar:hover { opacity: 0.7; }
.baseline-micro-bar--ok { background: #22c55e; }
.baseline-micro-bar--warn { background: #f59e0b; }
.baseline-micro-bar--error { background: #ef4444; }
.baseline-micro-bar--mismatch { background: #9333ea; }
.baseline-micro-bar--neutral { background: #94a3b8; }

/* ── Table ───────────────────────────────────────────── */
.baseline-table-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.baseline-search {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  width: 220px;
  background: #fff;
  color: #1e293b;
}
.baseline-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.baseline-filter-btn {
  padding: 4px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 20px;
  font-size: 12px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.baseline-filter-btn:hover { background: #f1f5f9; }
.baseline-filter-btn--active {
  background: #6366f1;
  color: #fff;
  border-color: #6366f1;
}

.baseline-table-wrap {
  overflow-x: auto;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.baseline-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.baseline-table thead tr {
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.baseline-table th {
  padding: 8px 12px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.baseline-table__row {
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background 0.1s;
}
.baseline-table__row:last-child { border-bottom: none; }
.baseline-table__row:hover { background: #f8fafc; }
.baseline-table__row--mismatch { background: #fdf4ff; }
.baseline-table__row--mismatch:hover { background: #fae8ff; }
.baseline-table__row--seed { opacity: 0.55; }
.baseline-table td {
  padding: 8px 12px;
  vertical-align: middle;
  color: #1e293b;
}
.baseline-table__id { font-family: monospace; font-size: 12px; }
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
  padding: 20px;
}

/* ── Status badges ───────────────────────────────────── */
.baseline-status-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.badge--success { background: #dcfce7; color: #15803d; }
.badge--error { background: #fee2e2; color: #b91c1c; }
.badge--blocked { background: #ede9fe; color: #6d28d9; }
.badge--clarification { background: #fef9c3; color: #92400e; }
.badge--neutral { background: #f1f5f9; color: #475569; }
.badge--running { background: #dbeafe; color: #1d4ed8; }
.badge--queued { background: #f0fdf4; color: #166534; }
.badge--mismatch { background: #fdf4ff; color: #7e22ce; }

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
  background: rgba(0,0,0,0.3);
}
.baseline-drawer__panel {
  position: relative;
  width: min(580px, 95vw);
  height: 100%;
  background: #fff;
  box-shadow: -4px 0 24px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.baseline-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.baseline-drawer__title {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: #0f172a;
}
.baseline-drawer__close {
  background: none;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: #64748b;
}
.baseline-drawer__close:hover { background: #f1f5f9; }
.baseline-drawer__close svg { width: 16px; height: 16px; }

.baseline-drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.baseline-drawer__row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 8px;
  font-size: 13px;
}
.baseline-drawer__key {
  flex-shrink: 0;
  width: 110px;
  font-weight: 500;
  color: #64748b;
  padding-top: 2px;
}
.baseline-drawer__val {
  flex: 1;
  color: #1e293b;
  word-break: break-word;
}
.baseline-drawer__val--error { color: #dc2626; }

.baseline-drawer__section {
  margin-top: 14px;
  border-top: 1px solid #f1f5f9;
  padding-top: 12px;
}
.baseline-drawer__section-title {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 8px;
}

/* ── Node trace ──────────────────────────────────────── */
.baseline-trace {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.baseline-trace__node {
  padding: 2px 8px;
  background: #f1f5f9;
  border-radius: 4px;
  font-size: 11px;
  color: #334155;
  font-family: monospace;
}

/* ── Detail table ────────────────────────────────────── */
.baseline-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.baseline-detail-table tr { border-bottom: 1px solid #f1f5f9; }
.baseline-detail-table td { padding: 4px 6px; color: #1e293b; }
.baseline-detail-table__key { color: #64748b; width: 140px; font-family: monospace; }

/* ── Pre blocks ──────────────────────────────────────── */
.baseline-pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 11px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
  color: #334155;
  margin: 0;
}
.baseline-pre--sql { color: #1e40af; }

/* ── Drawer transition ───────────────────────────────── */
.drawer-enter-active, .drawer-leave-active { transition: opacity 0.2s ease; }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-active .baseline-drawer__panel,
.drawer-leave-active .baseline-drawer__panel { transition: transform 0.2s ease; }
.drawer-enter-from .baseline-drawer__panel,
.drawer-leave-to .baseline-drawer__panel { transform: translateX(100%); }

/* ── Responsive ──────────────────────────────────────── */
@media (max-width: 640px) {
  .baseline-history { width: 140px; min-width: 120px; }
  .baseline-main { padding: 12px; }
  .baseline-cards { gap: 8px; }
  .baseline-card { min-width: 72px; padding: 10px 10px; }
  .baseline-card__value { font-size: 18px; }
  .baseline-search { width: 160px; }
  .baseline-charts-row { flex-direction: column; }
}
</style>
