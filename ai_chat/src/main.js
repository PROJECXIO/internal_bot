import { createApp, reactive } from "vue";
import App from "./App.vue";
import "./style.css";

import router from './router';
import resourceManager from "../../../doppio/libs/resourceManager";
import call from "../../../doppio/libs/controllers/call";
import { io } from "socket.io-client";
import Auth from "../../../doppio/libs/controllers/auth";

async function initApp() {
	// Fetch CSRF token from Frappe when Jinja didn't inject it (Vite dev server).
	if (!window.csrf_token || window.csrf_token.includes("{{")) {
		try {
			const res = await fetch("/api/method/frappe.auth.get_csrf_token", {
				method: "GET",
				headers: { Accept: "application/json" },
			});
			const data = await res.json();
			if (data.message) window.csrf_token = data.message;
		} catch {
			// Guest session — token will be set after login
		}
	}

	// doppio's socket.js hardcodes port 9000 and lacks proper namespace + credentials.
	// Frappe's socket.io server uses per-site namespaces (/<sitename>) and requires
	// withCredentials so the session cookie (sid) is sent for authentication.
	const _socketPort = (typeof window.socketio_port === "number" && window.socketio_port > 0)
		? window.socketio_port
		: 9000;

	function getValidSiteName(rawSiteName) {
		if (typeof rawSiteName !== "string") {
			return "";
		}

		const value = rawSiteName.trim();
		if (!value || value.includes("{{") || value.includes("}}")) {
			return "";
		}

		return value;
	}

	const _siteName = getValidSiteName(window.site_name) || window.location.hostname;
	const _socketProtocol = window.location.protocol === "https:" ? "https" : "http";
	const socket = io(`${_socketProtocol}://${window.location.hostname}:${_socketPort}/${_siteName}`, {
		withCredentials: true,
	});

	const app = createApp(App);
	const auth = reactive(new Auth());

	// Plugins
	app.use(router);
	app.use(resourceManager);

	// Global Properties,
	// components can inject this
	app.provide("$auth", auth);
	app.provide("$call", call);
	app.provide("$socket", socket);

	// Configure route guards
	router.beforeEach(async (to, from, next) => {
		if (to.matched.some((record) => !record.meta.isLoginPage)) {
			if (!auth.isLoggedIn) {
				next({ name: 'Login', query: { route: to.fullPath } });
			} else {
				next();
			}
		} else {
			if (auth.isLoggedIn) {
				next({ name: 'Home' });
			} else {
				next();
			}
		}
	});

	app.mount("#app");
}

initApp();
