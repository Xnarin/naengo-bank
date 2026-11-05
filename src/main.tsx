import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { BankProvider } from './store';
import 'wanted-sans/fonts/webfonts/variable/split/WantedSansVariable.css';
import '@fontsource/sora/600.css';
import '@fontsource/sora/700.css';
import './index.css';
import { applyTheme, savedTheme } from './lib/theme';

applyTheme(savedTheme());

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <BankProvider>
        <App />
      </BankProvider>
    </BrowserRouter>
  </StrictMode>,
);
