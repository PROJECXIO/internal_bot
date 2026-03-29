<template>
  <div class="flex flex-col h-full bg-white">
    <!-- Header -->
    <div class="flex items-center gap-3 px-5 py-3.5 border-b border-brand-light shrink-0 bg-white">
      <RevenyuLogo class="text-gray-900" />
      <div class="ml-auto">
        <button
          class="text-xs border border-gray-200 text-gray-600 rounded-lg px-3 py-1.5 hover:bg-gray-50 transition-colors"
          @click="$auth.logout()"
        >
          Sign out
        </button>
      </div>
    </div>

    <!-- Messages -->
    <MessageList
      ref="messageListRef"
      :messages="messages"
      :loading="loading"
      class="flex-1 min-h-0"
      @option="sendText"
    />

    <!-- Input -->
    <div class="shrink-0">
      <MessageInput
        v-model="inputText"
        :loading="loading"
        @send="send"
      />
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
    };
  },

  methods: {
    async send() {
      const text = this.inputText.trim();
      if (!text || this.loading) return;
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
          debug: false,
        });

        this.messages.push({
          role: "assistant",
          status: res.status,
          title: res.title || "",
          columns: res.columns || [],
          rows: res.rows || [],
          question: res.question || "",
          options: res.options || [],
          reason: res.reason || "",
          content: res.message || "",
        });
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
