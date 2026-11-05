import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// /agent 는 백엔드(FastAPI)로 넘긴다. .env 에 VITE_CHAT_API_URL=/agent 를 넣으면 AI 어시스턴트가 RAG 에이전트를 쓴다 (같은 출처라 CORS 불필요)
export default defineConfig({ plugins: [react(), tailwindcss()], server: { proxy: { '/agent': 'http://localhost:8000' } } });
