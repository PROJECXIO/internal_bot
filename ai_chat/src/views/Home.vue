<template>
  <div class="flex h-full flex-col bg-slate-50 md:flex-row">
    <aside class="session-sidebar shrink-0">
      <div class="session-sidebar__header">
        <RevenyuLogo class="text-gray-900" />
        <button
          class="session-sidebar__signout"
          @click="$auth.logout()"
        >
          Sign out
        </button>
      </div>

      <button
        class="session-sidebar__new"
        :disabled="loading || sessionLoading"
        @click="createNewSession"
      >
        New session
      </button>

      <div class="session-sidebar__list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="session-sidebar__item"
          :class="{ 'session-sidebar__item--active': session.session_id === currentSessionId }"
        >
          <button
            type="button"
            class="session-sidebar__item-main"
            :disabled="loading || sessionLoading"
            @click="selectSession(session.session_id)"
          >
            <div class="session-sidebar__item-title">
              {{ sessionLabel(session) }}
            </div>
            <div v-if="session.preview" class="session-sidebar__item-preview">
              {{ session.preview }}
            </div>
            <div v-else class="session-sidebar__item-preview session-sidebar__item-preview--muted">
              Empty conversation
            </div>
          </button>

          <button
            type="button"
            class="session-sidebar__item-delete"
            :disabled="loading || sessionLoading"
            title="Delete session"
            aria-label="Delete session"
            @click.stop="deleteSession(session.session_id)"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 6h18" />
              <path d="M8 6V4.8c0-.66.54-1.2 1.2-1.2h5.6c.66 0 1.2.54 1.2 1.2V6" />
              <path d="M6.5 6l1 13.2c.05.69.62 1.22 1.31 1.22h6.38c.69 0 1.26-.53 1.31-1.22L17.5 6" />
              <path d="M10 10.2v6.6" />
              <path d="M14 10.2v6.6" />
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col bg-white">
      <div class="flex items-center gap-3 px-5 py-3.5 border-b border-brand-light shrink-0 bg-white">
        <div class="flex items-center gap-2">
          <!-- Live status dot: pulses while a query is in flight -->
          <span
            class="inline-block w-2 h-2 rounded-full shrink-0"
            :class="loading ? 'bg-brand animate-pulse' : 'bg-brand'"
          />
        </div>
        <div>
          <p class="text-sm font-semibold text-slate-900">AI Chat</p>
          <p class="text-xs text-slate-500">
            {{ activeSessionSubtitle }}
          </p>
        </div>
      </div>

      <!-- Socket disconnect banner -->
      <ConnectionBanner :show="!socketConnected" />

      <MessageList
        ref="messageListRef"
        :messages="messages"
        :loading="loading || sessionLoading"
        :progress-steps="progressSteps"
        class="flex-1 min-h-0"
        @option="sendText"
      />

      <div class="shrink-0">
        <MessageInput
          v-model="inputText"
          :loading="loading || sessionLoading"
          @send="send"
        />
      </div>
    </div>
  </div>
</template>

<script>
import MessageList from "../components/MessageList.vue";
import MessageInput from "../components/MessageInput.vue";
import RevenyuLogo from "../components/RevenyuLogo.vue";
import ConnectionBanner from "../components/ConnectionBanner.vue";

export default {
  components: { MessageList, MessageInput, RevenyuLogo, ConnectionBanner },

  inject: ["$auth", "$call", "$socket"],

  data() {
    return {
      messages: [],
      inputText: "",
      loading: false,
      sessionLoading: false,
      currentSessionId: "",
      sessions: [],
      // Progress state
      progressSteps: [],
      socketConnected: true,
      // Track pending async job so we only act on events for the current request
      _pendingJobId: null,
      // Polling fallback timer (in case socket events don't arrive)
      _pollTimer: null,
      debugEnabled: false,
      _suppressRouteSessionWatch: false,
    };
  },

  async mounted() {
    await this.initializeSession();
    this.setupSocket();
  },

  beforeUnmount() {
    this.teardownSocket();
    this._stopPolling();
  },

  computed: {
    activeSession() {
      return this.sessions.find((session) => session.session_id === this.currentSessionId) || null;
    },

    activeSessionSubtitle() {
      if (this.sessionLoading) {
        return "Loading session...";
      }

      if (!this.activeSession) {
        return "Start a new conversation.";
      }

      const count = this.activeSession.total_messages || 0;
      return `${count} message${count === 1 ? "" : "s"} in this conversation`;
    },

  },

  watch: {
    "$route.query.session_id": {
      async handler(newSessionId) {
        if (this._suppressRouteSessionWatch) return;
        await this.handleRouteSessionChange(newSessionId);
      },
    },
  },

  methods: {
    // ── Socket setup ──────────────────────────────────────────────

    setupSocket() {
      this.$socket.on("bot_progress", (data) => {
        // Ignore events not for the current job or session
        if (data.session_id && data.session_id !== this.currentSessionId) return;
        if (data.job_id && this._pendingJobId && data.job_id !== this._pendingJobId) return;

        if (data.is_complete) {
          this._handleProgressComplete(data.response);
          return;
        }

        if (data.is_error) {
          this._handleProgressError();
          return;
        }

        // Mark the previous active step as done, push the new one
        const prev = [...this.progressSteps].reverse().find((s) => s.status === "active");
        if (prev) prev.status = "done";
        this.progressSteps.push({
          node: data.node,
          label: data.label,
          status: "active",
          attempt: data.attempt || 0,
        });

        this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
      });

      this.$socket.on("connect", () => {
        this.socketConnected = true;
      });
      this.$socket.on("disconnect", () => {
        this.socketConnected = false;
      });
    },

    teardownSocket() {
      this.$socket.off("bot_progress");
      this.$socket.off("connect");
      this.$socket.off("disconnect");
    },

    _stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    },

    _startPolling(jobId) {
      this._stopPolling();
      // Poll ask_status every 2s as a fallback when socket events don't arrive
      this._pollTimer = setInterval(async () => {
        if (!this._pendingJobId || this._pendingJobId !== jobId) {
          this._stopPolling();
          return;
        }
        try {
          const result = await this.$call("internal_bot.api.chat.ask_status", { job_id: jobId });
          if (result.status === "complete" && result.response) {
            this._stopPolling();
            this._handleProgressComplete(result.response);
          } else if (result.status === "error") {
            this._stopPolling();
            this._handleProgressError();
          }
          // status === "running" → keep polling
        } catch {
          // Polling failure is non-fatal — keep trying
        }
      }, 2000);
    },

    _handleProgressComplete(response) {
      // Guard against double-resolution (socket + poll both firing)
      if (!this._pendingJobId) return;
      this._stopPolling();
      // Mark all remaining active steps as done
      this.progressSteps.forEach((s) => { s.status = "done"; });

      // Brief pause so the user sees the last step complete, then render result
      setTimeout(() => {
        const finalize = async () => {
          this.progressSteps = [];
          this.loading = false;
          this._pendingJobId = null;

          if (response) {
            await this.syncSelectedSession(response.session_id || this.currentSessionId, { replace: true });
            this.messages.push(this.mapAssistantMessage(response));
            await this.refreshSessions();
          }

          this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
        };

        void finalize();
      }, 600);
    },

    _handleProgressError() {
      if (!this._pendingJobId) return;
      this._stopPolling();
      this.progressSteps = [];
      this.loading = false;
      this._pendingJobId = null;
      this.messages.push({
        role: "assistant",
        status: "error",
        reason: "Something went wrong. Please try again.",
      });
      this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
    },

    // ── Session management ────────────────────────────────────────

    normalizeSessionId(value) {
      return typeof value === "string" && value.trim() ? value.trim() : "";
    },

    getStoredSessionId() {
      return this.normalizeSessionId(window.localStorage.getItem("internal-bot-session-id"));
    },

    setStoredSessionId(sessionId) {
      const normalized = this.normalizeSessionId(sessionId);
      if (normalized) {
        window.localStorage.setItem("internal-bot-session-id", normalized);
        return;
      }

      window.localStorage.removeItem("internal-bot-session-id");
    },

    clearSessionView() {
      this.currentSessionId = "";
      this.messages = [];
      this.inputText = "";
    },

    async syncSelectedSession(sessionId, { replace = false, syncStorage = true } = {}) {
      const normalized = this.normalizeSessionId(sessionId);

      this.currentSessionId = normalized;
      if (syncStorage) {
        this.setStoredSessionId(normalized);
      }

      const currentRouteSessionId = this.normalizeSessionId(this.$route?.query?.session_id);
      if (currentRouteSessionId === normalized) {
        return;
      }

      const query = { ...this.$route.query };
      if (normalized) {
        query.session_id = normalized;
      } else {
        delete query.session_id;
      }

      this._suppressRouteSessionWatch = true;
      try {
        await this.$router[replace ? "replace" : "push"]({ name: "Home", query });
      } catch {
        // Ignore navigation duplication failures
      } finally {
        this._suppressRouteSessionWatch = false;
      }
    },

    async loadPreferredSession(sessionIds) {
      const routeSessionId = this.normalizeSessionId(this.$route?.query?.session_id);

      for (const sessionId of sessionIds) {
        if (!sessionId) continue;

        try {
          await this.loadSession(sessionId, { replaceUrl: true });
          return true;
        } catch {
          if (sessionId === routeSessionId) {
            await this.syncSelectedSession(null, { replace: true, syncStorage: false });
          }
        }
      }

      return false;
    },

    async initializeSession() {
      this.sessionLoading = true;
      try {
        await this.loadDebugSettings();
        const routeSessionId = this.normalizeSessionId(this.$route?.query?.session_id);
        const storedSessionId = this.getStoredSessionId();
        const loaded = await this.loadPreferredSession(
          [routeSessionId, storedSessionId].filter((sessionId, index, all) => (
            sessionId && all.indexOf(sessionId) === index
          ))
        );

        if (!loaded) {
          await this.loadSession(null, { replaceUrl: true });
        }

        await this.refreshSessions();
      } finally {
        this.sessionLoading = false;
      }
    },

    mapAssistantMessage(payload) {
      return {
        role: "assistant",
        status: payload.status || "",
        responseType: payload.response_type || "",
        visualization: payload.visualization || null,
        answerPrefix: payload.answer_prefix || "",
        summary: payload.summary || "",
        markdown: payload.markdown || "",
        title: payload.title || "",
        columns: payload.columns || [],
        rows: payload.rows || [],
        question: payload.question || "",
        options: payload.options || [],
        reason: payload.reason || "",
        content: payload.message || payload.content || "",
        meta: payload.meta || {},
        debug: payload.debug || null,
      };
    },

    async loadDebugSettings() {
      try {
        const res = await this.$call(
          "internal_bot.internal_bot.doctype.ai_provider_settings.ai_provider_settings.get_chat_debug_settings"
        );
        this.debugEnabled = Boolean(res?.enable_debug_context_window);
      } catch {
        this.debugEnabled = false;
      }
    },

    async refreshSessions() {
      const res = await this.$call("internal_bot.api.chat.list_sessions");
      this.sessions = res.sessions || [];
    },

    async loadSession(sessionId = null, { replaceUrl = false, syncStorage = true } = {}) {
      const res = await this.$call("internal_bot.api.chat.get_session_history", {
        session_id: sessionId,
      });
      await this.syncSelectedSession(res.session_id || "", { replace: replaceUrl, syncStorage });
      this.messages = (res.messages || []).map((message) => {
        if (message.role === "assistant") {
          return this.mapAssistantMessage(message);
        }
        return {
          role: message.role,
          content: message.content || "",
          status: message.status || "",
        };
      });
      this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
    },

    async handleRouteSessionChange(newSessionId) {
      const nextSessionId = this.normalizeSessionId(newSessionId);
      if (nextSessionId === this.normalizeSessionId(this.currentSessionId)) return;

      if (!nextSessionId) {
        this.clearSessionView();
        this.setStoredSessionId(null);
        return;
      }

      this.sessionLoading = true;
      try {
        const storedSessionId = this.getStoredSessionId();

        try {
          await this.loadSession(nextSessionId, { replaceUrl: true });
        } catch {
          await this.syncSelectedSession(null, { replace: true, syncStorage: false });

          if (storedSessionId && storedSessionId !== nextSessionId) {
            try {
              await this.loadSession(storedSessionId, { replaceUrl: true });
              await this.refreshSessions();
              return;
            } catch {
              // Fall through to the backend default session
            }
          }

          await this.loadSession(null, { replaceUrl: true });
        }

        await this.refreshSessions();
      } finally {
        this.sessionLoading = false;
      }
    },

    async selectSession(sessionId) {
      if (!sessionId || sessionId === this.currentSessionId) return;
      this.sessionLoading = true;
      try {
        await this.loadSession(sessionId);
      } finally {
        this.sessionLoading = false;
      }
    },

    async ensureSessionSelected() {
      if (this.currentSessionId) {
        return this.currentSessionId;
      }

      const res = await this.$call("internal_bot.api.chat.create_session");
      await this.syncSelectedSession(res.session_id || "", { replace: true });
      await this.refreshSessions();
      return this.currentSessionId;
    },

    async createNewSession() {
      this.sessionLoading = true;
      try {
        const res = await this.$call("internal_bot.api.chat.create_session");
        await this.syncSelectedSession(res.session_id || "");
        this.messages = [];
        this.inputText = "";
        await this.refreshSessions();
      } finally {
        this.sessionLoading = false;
      }
    },

    async deleteSession(sessionId) {
      if (!sessionId || this.loading || this.sessionLoading) return;

      const confirmed = window.confirm("Delete this session permanently? This action cannot be undone.");
      if (!confirmed) return;

      this.sessionLoading = true;
      try {
        await this.$call("internal_bot.api.chat.delete_session", {
          session_id: sessionId,
        });

        if (sessionId === this.currentSessionId) {
          this.clearSessionView();
          await this.syncSelectedSession(null, { replace: true });
        }

        await this.refreshSessions();
      } catch (err) {
        window.alert(err?.messages?.[0] || "Could not delete the session.");
      } finally {
        this.sessionLoading = false;
      }
    },

    sessionLabel(session) {
      const date = new Date(session.modified || session.creation);
      const when = Number.isNaN(date.getTime())
        ? "Session"
        : date.toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
          });
      const count = session.total_messages || 0;
      return `${when} (${count} msg)`;
    },

    async send() {
      const text = this.inputText.trim();
      if (!text || this.loading || this.sessionLoading) return;
      await this.sendText(text);
    },

    async sendText(text) {
      this.inputText = "";
      this.messages.push({ role: "user", content: text });
      this.loading = true;
      this.progressSteps = [];
      this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());

      try {
        const activeSessionId = await this.ensureSessionSelected();

        // Use the async endpoint: returns immediately with job_id
        const queued = await this.$call("internal_bot.api.chat.ask_async", {
          message: text,
          session_id: activeSessionId || null,
          debug: this.debugEnabled,
        });

        // Update session_id immediately so socket events are matched correctly
        if (queued.session_id) {
          await this.syncSelectedSession(queued.session_id, { replace: true });
        }

        // Track the pending job for event filtering
        this._pendingJobId = queued.job_id || null;

        // Start polling fallback: delivers the answer even if socket events
        // don't arrive (e.g. wrong port, proxy blocking WebSocket upgrades).
        // The poll is cancelled as soon as a socket event or poll response resolves.
        if (this._pendingJobId) {
          this._startPolling(this._pendingJobId);
        }

      } catch (err) {
        this.progressSteps = [];
        this.loading = false;
        this._pendingJobId = null;
        this.messages.push({
          role: "assistant",
          status: "error",
          reason: err?.messages?.[0] || "Something went wrong. Please try again.",
        });
        this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
      }
    },
  },
};
</script>
