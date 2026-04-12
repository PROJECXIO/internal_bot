import { createRouter, createWebHistory } from "vue-router";
import Home from "../views/Home.vue";
import BaselineDashboard from "../views/BaselineDashboard.vue";
import authRoutes from './auth';

const routes = [
  {
    path: "/",
    name: "Home",
    component: Home,
  },
  {
    path: "/baseline",
    name: "Baseline",
    component: BaselineDashboard,
  },
  ...authRoutes,
];

const router = createRouter({
  history: createWebHistory("/ai_chat"),
  routes,
});

export default router;
