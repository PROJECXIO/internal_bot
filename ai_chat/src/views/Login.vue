<template>
  <div class="min-h-screen bg-gradient-to-br from-white via-emerald-50/40 to-teal-50/60 flex items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <!-- Logo + heading -->
      <div class="text-center mb-8">
        <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-white shadow-lg shadow-teal-100 mb-5">
          <RevenyuCut class="w-8 h-8" />
        </div>
        <h1 class="text-xl font-bold text-gray-900 tracking-tight">Sign in to AI Chat</h1>
        <p class="mt-1.5 text-sm text-gray-500">Enter your credentials to continue</p>
      </div>

      <!-- Card -->
      <div class="bg-white rounded-2xl shadow-xl shadow-teal-900/[0.06] border border-gray-100 p-6">
        <form @submit.prevent="login" class="space-y-4">
          <div>
            <label for="email" class="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
              Email or Username
            </label>
            <input
              id="email"
              type="text"
              v-model="email"
              placeholder="you@company.com"
              autocomplete="username"
              class="w-full px-3.5 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </div>

          <div>
            <label for="password" class="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
              Password
            </label>
            <input
              id="password"
              type="password"
              v-model="password"
              placeholder="Enter your password"
              autocomplete="current-password"
              class="w-full px-3.5 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </div>

          <p v-if="errorMessage" class="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">
            {{ errorMessage }}
          </p>

          <button
            type="submit"
            :disabled="loading"
            class="w-full py-2.5 rounded-xl text-sm font-semibold text-white transition-all cursor-pointer"
            :class="loading
              ? 'bg-brand/60 cursor-not-allowed'
              : 'bg-brand hover:bg-brand-dark shadow-lg shadow-brand/25 hover:shadow-brand/35 active:scale-[0.98]'"
          >
            <span v-if="loading" class="inline-flex items-center gap-2">
              <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Signing in...
            </span>
            <span v-else>Sign in</span>
          </button>
        </form>
      </div>

      <p class="mt-6 text-center text-xs text-gray-400">
        Powered by Revenyu AI
      </p>
    </div>
  </div>
</template>

<script>
import RevenyuCut from "../components/RevenyuCut.vue";

export default {
  components: { RevenyuCut },
  data() {
    return {
      email: null,
      password: null,
      loading: false,
      errorMessage: null,
    };
  },
  inject: ["$auth"],
  async mounted() {
    if (this.$route?.query?.route) {
      this.redirect_route = this.$route.query.route;
      this.$router.replace({ query: null });
    }
  },
  methods: {
    async login() {
      if (!this.email || !this.password) return;
      this.errorMessage = null;
      this.loading = true;
      try {
        let res = await this.$auth.login(this.email, this.password);
        if (res) {
          // Refresh CSRF token after login
          try {
            const tokenRes = await fetch("/api/method/frappe.auth.get_csrf_token", {
              method: "GET",
              headers: { Accept: "application/json" },
            });
            const data = await tokenRes.json();
            if (data.message) window.csrf_token = data.message;
          } catch { /* ignore */ }
          this.$router.push({ name: "Home" });
        }
      } catch (e) {
        this.errorMessage = e.messages?.[0] || "Login failed. Please check your credentials.";
      } finally {
        this.loading = false;
      }
    },
  },
};
</script>
