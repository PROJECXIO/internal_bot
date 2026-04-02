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
        <button
          v-for="session in sessions"
          :key="session.session_id"
          class="session-sidebar__item"
          :class="{ 'session-sidebar__item--active': session.session_id === currentSessionId }"
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
        this.progressSteps = [];
        this.loading = false;
        this._pendingJobId = null;

        if (response) {
          this.currentSessionId = response.session_id || this.currentSessionId;
          window.localStorage.setItem("internal-bot-session-id", this.currentSessionId);
          this.messages.push(this.mapAssistantMessage(response));
          this.refreshSessions();
        }

        this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
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

    async initializeSession() {
      this.sessionLoading = true;
      try {
        const storedSessionId = window.localStorage.getItem("internal-bot-session-id");
        try {
          await this.loadSession(storedSessionId);
        } catch {
          await this.loadSession();
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
        title: payload.title || "",
        columns: payload.columns || [],
        rows: payload.rows || [],
        question: payload.question || "",
        options: payload.options || [],
        reason: payload.reason || "",
        content: payload.message || payload.content || "",
        meta: payload.meta || {},
      };
    },

    async refreshSessions() {
      const res = await this.$call("internal_bot.api.chat.list_sessions");
      this.sessions = res.sessions || [];
      if (!this.currentSessionId && res.active_session_id) {
        this.currentSessionId = res.active_session_id;
      }
    },

    async loadSession(sessionId = null) {
      const res = await this.$call("internal_bot.api.chat.get_session_history", {
        session_id: sessionId,
      });
      this.currentSessionId = res.session_id || "";
      window.localStorage.setItem("internal-bot-session-id", this.currentSessionId);
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

    async selectSession(sessionId) {
      if (!sessionId || sessionId === this.currentSessionId) return;
      this.currentSessionId = sessionId;
      this.sessionLoading = true;
      try {
        await this.loadSession(sessionId);
      } finally {
        this.sessionLoading = false;
      }
    },

    async createNewSession() {
      this.sessionLoading = true;
      try {
        const res = await this.$call("internal_bot.api.chat.create_session");
        this.currentSessionId = res.session_id || "";
        window.localStorage.setItem("internal-bot-session-id", this.currentSessionId);
        this.messages = [];
        this.inputText = "";
        await this.refreshSessions();
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
        // Use the async endpoint: returns immediately with job_id
        const queued = await this.$call("internal_bot.api.chat.ask_async", {
          message: text,
          session_id: this.currentSessionId || null,
          debug: false,
        });

        // Update session_id immediately so socket events are matched correctly
        if (queued.session_id) {
          this.currentSessionId = queued.session_id;
          window.localStorage.setItem("internal-bot-session-id", this.currentSessionId);
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
