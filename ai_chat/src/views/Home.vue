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
        <div>
          <p class="text-sm font-semibold text-slate-900">AI Chat</p>
          <p class="text-xs text-slate-500">
            {{ activeSessionSubtitle }}
          </p>
        </div>
      </div>

      <MessageList
        ref="messageListRef"
        :messages="messages"
        :loading="loading || sessionLoading"
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

export default {
  components: { MessageList, MessageInput, RevenyuLogo },

  inject: ["$auth", "$call"],

  data() {
    return {
      messages: [],
      inputText: "",
      loading: false,
      sessionLoading: false,
      currentSessionId: "",
      sessions: [],
    };
  },

  async mounted() {
    await this.initializeSession();
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
      this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());

      try {
        const res = await this.$call("internal_bot.api.chat.ask", {
          message: text,
          session_id: this.currentSessionId || null,
          debug: false,
        });

        this.currentSessionId = res.session_id || this.currentSessionId;
        window.localStorage.setItem("internal-bot-session-id", this.currentSessionId);
        this.messages.push(this.mapAssistantMessage(res));
        await this.refreshSessions();
      } catch (err) {
        this.messages.push({
          role: "assistant",
          status: "error",
          reason: err?.messages?.[0] || "Something went wrong. Please try again.",
        });
      } finally {
        this.loading = false;
        this.$nextTick(() => this.$refs.messageListRef?.scrollToBottom());
      }
    },
  },
};
</script>
