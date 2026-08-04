import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // 8080 é a porta same-origin do nginx (serviço `frontend`); a API não é exposta no host.
    // `/ws` precisa de `ws: true` e do path literal sem barra final (spec F3 §5.3): o
    // `location /ws` do nginx casa por prefixo e `/ws/` chega ao Starlette como 403.
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/ws": { target: "ws://127.0.0.1:8080", ws: true },
    },
  },
});
