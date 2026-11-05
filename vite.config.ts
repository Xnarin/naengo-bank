import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// 모든 은행·에이전트 요청은 같은 출처의 /api를 통해 Docker FastAPI에 전달한다.
export default defineConfig({ plugins: [react(), tailwindcss()], server: { proxy: {
  '/api': { target: 'http://127.0.0.1:8001', rewrite: (path) => path.replace(/^\/api/, '') },
} } });
